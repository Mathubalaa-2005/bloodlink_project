"""
app_aws.py
Flask application for BloodSync using AWS DynamoDB as the backend storage.
SNS removed as requested — no notifications are sent.

Notes:
- The app attempts to use DynamoDB tables named: Donors, Requestors, BloodRequests,
  Donations, Assignments, Inventory. If tables are not reachable the app falls
  back to in-memory dictionaries to avoid crashing during local development.
"""
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
from decimal import Decimal
import uuid
import os
import json
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

app = Flask(__name__)
app.secret_key = 'bloodsync-aws-key'

# AWS Configuration
REGION = os.environ.get('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=REGION)

# Table names used by this app
TABLE_NAMES = {
    'donors': 'Donors',
    'requestors': 'Requestors',
    'requests': 'BloodRequests',
    'donations': 'Donations',
    'assignments': 'Assignments',
    'inventory': 'Inventory'
}

# Try to obtain table objects; if not available, fall back to in-memory stores
def _get_table(name):
    try:
        return dynamodb.Table(name)
    except Exception:
        return None

tables = {k: _get_table(v) for k, v in TABLE_NAMES.items()}

# In-memory fallbacks
donors_db = {}
requestors_db = {}
blood_requests_db = {}
donations_db = {}
assignments_db = {}
inventory_db = {}
registrations_db = {}

# Data directory for simple file persistence (fallback)
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, 'data')

def _load_json_file(name):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def _save_json_file(name, data):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# attempt to seed in-memory stores from data files if present
_seed = _load_json_file('donors.json')
if isinstance(_seed, list):
    for d in _seed:
        donors_db[d.get('donor_id')] = d
_seed = _load_json_file('inventory.json')
if isinstance(_seed, list):
    for i in _seed:
        # inventory items keyed by blood_group if no id
        key = i.get('blood_group') or i.get('group') or i.get('inventory_id') or str(len(inventory_db)+1)
        inventory_db[key] = i
_seed = _load_json_file('donor_registrations.json')
if isinstance(_seed, list):
    for r in _seed:
        registrations_db[r.get('registration_id')] = r

# Compatibility data (same as in the main app)
BLOOD_COMPATIBILITY = {
    'A+': ['A+', 'AB+'],
    'A-': ['A+', 'A-', 'AB+', 'AB-'],
    'B+': ['B+', 'AB+'],
    'B-': ['B+', 'B-', 'AB+', 'AB-'],
    'AB+': ['AB+'],
    'AB-': ['AB+', 'AB-'],
    'O+': ['O+', 'A+', 'B+', 'AB+'],
    'O-': ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']
}

RECEIVE_COMPATIBILITY = {
    'A+': ['A+', 'A-', 'O+', 'O-'],
    'A-': ['A-', 'O-'],
    'B+': ['B+', 'B-', 'O+', 'O-'],
    'B-': ['B-', 'O-'],
    'AB+': ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'],
    'AB-': ['A-', 'B-', 'AB-', 'O-'],
    'O+': ['O+', 'O-'],
    'O-': ['O-']
}

# --- DynamoDB helper functions with fallback ---
def db_get(table_key, key):
    t = tables.get(table_key)
    if t:
        try:
            resp = t.get_item(Key=key)
            return resp.get('Item')
        except (ClientError, NoCredentialsError):
            # AWS call failed or no credentials configured — fall back to in-memory
            pass
    # fallback
    if table_key == 'donors':
        return donors_db.get(key.get('donor_id'))
    if table_key == 'requestors':
        return requestors_db.get(key.get('requestor_id'))
    if table_key == 'requests':
        return blood_requests_db.get(key.get('request_id'))
    if table_key == 'donor_registrations':
        return registrations_db.get(key.get('registration_id'))
    return None

def db_put(table_key, item):
    t = tables.get(table_key)
    if t:
        try:
            # DynamoDB does not accept Python floats; convert floats to Decimal
            def _convert_floats_to_decimal(obj):
                if isinstance(obj, dict):
                    return {k: _convert_floats_to_decimal(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_convert_floats_to_decimal(v) for v in obj]
                if isinstance(obj, float):
                    return Decimal(str(obj))
                return obj

            safe_item = _convert_floats_to_decimal(item)
            t.put_item(Item=safe_item)
            return True
        except (ClientError, NoCredentialsError):
            # Fall back to in-memory on AWS errors or missing credentials
            pass
    # fallback
    if table_key == 'donors':
        donors_db[item['donor_id']] = item
        # persist donors list to data/donors.json for local visibility
        try:
            _save_json_file('donors.json', list(donors_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'requestors':
        requestors_db[item['requestor_id']] = item
        try:
            _save_json_file('requestors.json', list(requestors_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'requests':
        blood_requests_db[item['request_id']] = item
        try:
            _save_json_file('blood_requests.json', list(blood_requests_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'donations':
        donations_db[item['donation_id']] = item
        try:
            _save_json_file('donations.json', list(donations_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'assignments':
        assignments_db[item['assignment_id']] = item
        try:
            _save_json_file('assignments.json', list(assignments_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'donor_registrations':
        registrations_db[item['registration_id']] = item
        try:
            _save_json_file('donor_registrations.json', list(registrations_db.values()))
        except Exception:
            pass
        return True
    if table_key == 'inventory':
        # key by blood_group where possible
        key = item.get('blood_group') or item.get('inventory_id') or str(len(inventory_db) + 1)
        inventory_db[key] = item
        try:
            _save_json_file('inventory.json', list(inventory_db.values()))
        except Exception:
            pass
        return True
    return False

def db_scan(table_key):
    # First, reload from JSON files to ensure fresh data across all pages
    global donors_db, requestors_db, blood_requests_db, donations_db, assignments_db, inventory_db, registrations_db
    
    if table_key == 'donors':
        seed = _load_json_file('donors.json')
        if isinstance(seed, list):
            donors_db = {}
            for d in seed:
                donors_db[d.get('donor_id')] = d
        return list(donors_db.values())
    elif table_key == 'requestors':
        seed = _load_json_file('requestors.json')
        if isinstance(seed, list):
            requestors_db = {}
            for r in seed:
                requestors_db[r.get('requestor_id')] = r
        return list(requestors_db.values())
    elif table_key == 'requests':
        seed = _load_json_file('blood_requests.json')
        if isinstance(seed, list):
            blood_requests_db = {}
            for r in seed:
                blood_requests_db[r.get('request_id')] = r
        return list(blood_requests_db.values())
    elif table_key == 'donations':
        seed = _load_json_file('donations.json')
        if isinstance(seed, list):
            donations_db = {}
            for d in seed:
                donations_db[d.get('donation_id')] = d
        return list(donations_db.values())
    elif table_key == 'assignments':
        seed = _load_json_file('assignments.json')
        if isinstance(seed, list):
            assignments_db = {}
            for a in seed:
                assignments_db[a.get('assignment_id')] = a
        return list(assignments_db.values())
    elif table_key == 'donor_registrations':
        seed = _load_json_file('donor_registrations.json')
        if isinstance(seed, list):
            registrations_db = {}
            for r in seed:
                registrations_db[r.get('registration_id')] = r
        return list(registrations_db.values())
    elif table_key == 'inventory':
        seed = _load_json_file('inventory.json')
        if isinstance(seed, list):
            inventory_db = {}
            for i in seed:
                key = i.get('blood_group') or i.get('group') or i.get('inventory_id') or str(len(inventory_db)+1)
                inventory_db[key] = i
        return list(inventory_db.values())
    return []

# --- Utility functions (adapted from original app) ---
def generate_id(prefix='ID'):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"

def can_donate(last_donation_date):
    if not last_donation_date:
        return True
    try:
        last = datetime.strptime(last_donation_date, '%Y-%m-%d')
        return (datetime.now() - last).days >= 56
    except Exception:
        return True

def calculate_donor_eligibility(donor):
    score = 100
    age = donor.get('age', 0)
    if 25 <= age <= 45:
        score += 10
    elif age < 18 or age > 65:
        score -= 50
    if not donor.get('available', True):
        score -= 100
    last_donation = donor.get('last_donation')
    if last_donation:
        try:
            days_since = (datetime.now() - datetime.strptime(last_donation, '%Y-%m-%d')).days
            if days_since > 90:
                score += 5
        except Exception:
            pass
    else:
        score += 10
    total_donations = donor.get('total_donations', 0)
    score += min(total_donations * 2, 20)
    return max(0, min(score, 150))

def get_compatible_donors(recipient_blood_group, location=None):
    compatible_bgs = RECEIVE_COMPATIBILITY.get(recipient_blood_group, [])
    donors = db_scan('donors')
    results = []
    for d in donors:
        if d.get('blood_group') in compatible_bgs and d.get('available') and d.get('status') == 'active':
            if location:
                if location.lower() in d.get('city', '').lower() or location.lower() in d.get('state', '').lower():
                    results.append(d)
            else:
                results.append(d)
    results.sort(key=lambda x: (x.get('last_donation') or '1900-01-01'), reverse=True)
    return results

def match_blood_request(request_data):
    blood_group = request_data['blood_group']
    units_needed = request_data['units_needed']
    location = request_data.get('location', '')
    compatible_donors = get_compatible_donors(blood_group, location)
    scored = []
    for donor in compatible_donors:
        scored.append({
            **donor,
            'match_score': calculate_donor_eligibility(donor),
            'can_donate_now': can_donate(donor.get('last_donation'))
        })
    scored.sort(key=lambda x: x['match_score'], reverse=True)
    inventory_items = db_scan('inventory')
    inventory_map = {i['blood_group']: int(i.get('units', 0)) for i in inventory_items}
    inventory_available = inventory_map.get(blood_group, 0)
    remaining_units = units_needed - request_data.get('fulfilled_units', 0)
    return {
        'exact_match_inventory': inventory_available,
        'compatible_donors': scored[:10],
        'total_compatible': len(scored),
        'fulfillable': inventory_available >= remaining_units or len(scored) > 0,
        'remaining_units': remaining_units
    }

# --- Routes (minimal set mirroring original app) ---
@app.route('/')
def home():
    recent = sorted(db_scan('requests'), key=lambda x: x.get('created_at') or '', reverse=True)[:5]
    requests_list = db_scan('requests')
    inventory_items = db_scan('inventory')

    # build inventory map expected by templates (ensure all blood groups present)
    inventory_map = {}
    for item in inventory_items:
        bg = item.get('blood_group') or item.get('group') or 'Unknown'
        inventory_map[bg] = {
            'units': int(item.get('units', 0)),
            'donors': item.get('donors') or []
        }

    # ensure every standard blood group exists in inventory_map
    BLOOD_GROUPS = sorted(set(list(BLOOD_COMPATIBILITY.keys()) + list(RECEIVE_COMPATIBILITY.keys())))
    for bg in BLOOD_GROUPS:
        inventory_map.setdefault(bg, {'units': 0, 'donors': []})

    stats = {
        'total_donors': len(db_scan('donors')),
        'total_requests': len(requests_list),
        'fulfilled_requests': sum(1 for r in requests_list if r.get('status') == 'fulfilled'),
        'total_units': sum(int(i.get('units', 0)) for i in inventory_items),
        'inventory': inventory_map
    }
    return render_template('index.html', recent_requests=recent, stats=stats)

@app.route('/donor/register', methods=['GET', 'POST'])
def donor_register():
    if request.method == 'POST':
        donor_id = generate_id('DON')
        donor = {
            'donor_id': donor_id,
            'name': request.form['name'],
            'email': request.form['email'],
            'phone': request.form['phone'],
            'age': int(request.form.get('age', 0)),
            'gender': request.form.get('gender', ''),
            'blood_group': request.form.get('blood_group', ''),
            'weight': float(request.form.get('weight', 0)),
            'address': request.form.get('address', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'pincode': request.form.get('pincode', ''),
            'medical_history': request.form.get('medical_history', 'None'),
            'available': True,
            'status': 'active',
            'total_donations': 0,
            'last_donation': None,
            'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        db_put('donors', donor)
        # record registration history
        reg = {
            'registration_id': generate_id('REG'),
            'donor_id': donor_id,
            'name': donor.get('name'),
            'email': donor.get('email'),
            'blood_group': donor.get('blood_group'),
            'city': donor.get('city'),
            'state': donor.get('state'),
            'registered_at': donor.get('registered_at')
        }
        db_put('donor_registrations', reg)
        # set session then show explicit registration success page
        session['donor_id'] = donor_id
        flash(f'Registered. Donor ID: {donor_id}', 'success')
        return redirect(url_for('registration_success', role='donor', entity_id=donor_id))
    return render_template('donor_register.html')

@app.route('/request-blood', methods=['GET', 'POST'])
def request_blood():
    if request.method == 'POST':
        request_id = generate_id('BR')
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        req = {
            'request_id': request_id,
            'requestor_id': request.form.get('requestor_id', 'GUEST'),
            'patient_name': request.form['patient_name'],
            'blood_group': request.form['blood_group'],
            'units_needed': int(request.form['units_needed']),
            'hospital_name': request.form.get('hospital_name', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'contact_name': request.form.get('contact_name', ''),
            'contact_phone': request.form.get('contact_phone', ''),
            'urgency': request.form.get('urgency', 'normal'),
            'required_date': request.form.get('required_date', ''),
            'status': 'pending',
            'created_at': current_time,
            'matched_donors': [],
            'fulfilled_units': 0,
            'inventory_used': 0
        }
        db_put('requests', req)
        match = match_blood_request(req)
        req['matched_donors'] = [d.get('donor_id') for d in match['compatible_donors']]
        db_put('requests', req)
        # Ensure database is persisted
        _save_json_file('blood_requests.json', list(blood_requests_db.values()))
        flash(f'Request created: {request_id}', 'success')
        return redirect(url_for('request_success', request_id=request_id))
    return render_template('request_blood.html')

@app.route('/request/<request_id>')
def request_details(request_id):
    req = db_get('requests', {'request_id': request_id})
    if not req:
        flash('Request not found', 'error')
        return redirect(url_for('home'))
    match = match_blood_request(req)
    return render_template('request_details.html', request=req, match_results=match)


@app.route('/fulfill/<request_id>', methods=['POST'])
def fulfill_request(request_id):
    req = db_get('requests', {'request_id': request_id})
    if not req:
        flash('Request not found', 'error')
        return redirect(url_for('home'))

    try:
        units = int(request.form.get('units_fulfilled', 0))
    except Exception:
        units = 0

    # Update fulfilled units and status
    req['fulfilled_units'] = req.get('fulfilled_units', 0) + units
    if req['fulfilled_units'] >= req.get('units_needed', 0):
        req['status'] = 'fulfilled'
    else:
        req['status'] = 'partial'

    # Reduce inventory if present
    inventory_items = db_scan('inventory')
    for item in inventory_items:
        bg = item.get('blood_group') or item.get('group')
        if bg and bg == req.get('blood_group'):
            cur = int(item.get('units', 0))
            item['units'] = max(0, cur - units)
            item['fulfilled_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db_put('inventory', item)
            # Ensure persistence
            _save_json_file('inventory.json', list(inventory_db.values()))
            break

    db_put('requests', req)
    _save_json_file('blood_requests.json', list(blood_requests_db.values()))
    flash('Request updated and inventory reduced', 'success')
    return redirect(url_for('request_details', request_id=request_id))

@app.route('/api/statistics')
def api_statistics():
    donors = db_scan('donors')
    requests = db_scan('requests')
    inventory = db_scan('inventory')
    total_units = sum(int(i.get('units', 0)) for i in inventory)
    return jsonify({
        'total_donors': len(donors),
        'total_requests': len(requests),
        'total_units': total_units
    })


# Minimal auth/dashboard routes so templates using url_for() don't fail
@app.route('/donor/login', methods=['GET', 'POST'])
def donor_login():
    if request.method == 'POST':
        donor_id = request.form.get('donor_id', '').strip()
        if donor_id:
            # Verify donor exists
            donor = db_get('donors', {'donor_id': donor_id})
            if donor:
                session['donor_id'] = donor_id
                flash(f'Welcome, {donor.get("name")}!', 'success')
                return redirect(url_for('donor_dashboard'))
            else:
                flash('Donor ID not found. Please register first.', 'error')
        else:
            flash('Please enter your Donor ID', 'error')
    return render_template('donor_login.html')


@app.route('/donor/dashboard')
def donor_dashboard():
    donor_id = session.get('donor_id')
    donor = None
    if donor_id:
        donor = db_get('donors', {'donor_id': donor_id})

    # Donation history and simple availability for template
    donations = db_scan('donations')
    # prepare a small recent donations list for template (pre-sorted and sliced)
    recent_donations = sorted(donations, key=lambda x: x.get('donation_date') or '', reverse=True)[:10]
    donation_history = [d for d in donations if d.get('donor_id') == donor_id] if donor_id else []
    can_donate_now = can_donate(donor.get('last_donation')) if donor else False

    # Available requests donor can help (simple compatibility check)
    available_requests = []
    if donor:
        donor_bg = donor.get('blood_group')
        can_donate_to = BLOOD_COMPATIBILITY.get(donor_bg, [])
        for r in db_scan('requests'):
            if r.get('blood_group') in can_donate_to and r.get('status') in ['pending', 'partial']:
                remaining = r.get('units_needed', 0) - r.get('fulfilled_units', 0)
                available_requests.append({**r, 'remaining_units': remaining})

    # Assigned requests - not implemented: provide empty list to satisfy template
    assigned_requests = []

    return render_template('donor_dashboard.html', donor=donor, donation_history=donation_history,
                           can_donate_now=can_donate_now, assigned_requests=assigned_requests,
                           available_requests=available_requests)


@app.route('/requestor/login', methods=['GET', 'POST'])
def requestor_login():
    if request.method == 'POST':
        requestor_id = request.form.get('requestor_id', '').strip()
        if requestor_id:
            # Verify requestor exists
            requestor = db_get('requestors', {'requestor_id': requestor_id})
            if requestor:
                session['requestor_id'] = requestor_id
                flash(f'Welcome, {requestor.get("name")}!', 'success')
                return redirect(url_for('requestor_dashboard'))
            else:
                flash('Requestor ID not found. Please register first.', 'error')
        else:
            flash('Please enter your Requestor ID', 'error')
    return render_template('requestor_login.html')


@app.route('/requestor/dashboard')
def requestor_dashboard():
    requestor_id = session.get('requestor_id')
    requestor = None
    if requestor_id:
        requestor = db_get('requestors', {'requestor_id': requestor_id})
    # Minimal context to satisfy template expectations
    my_requests = [r for r in db_scan('requests') if r.get('requestor_id') == requestor_id] if requestor_id else []
    stats = {
        'total_donors': len(db_scan('donors')),
        'total_requests': len(db_scan('requests')),
        'total_units': sum(int(i.get('units', 0)) for i in db_scan('inventory'))
    }
    return render_template('requestor_dashboard.html', requestor=requestor, my_requests=my_requests, stats=stats)


# Register as requestor
@app.route('/requestor/register', methods=['GET', 'POST'])
def requestor_register():
    if request.method == 'POST':
        requestor_id = generate_id('REQ')
        req = {
            'requestor_id': requestor_id,
            'name': request.form.get('name'),
            'email': request.form.get('email'),
            'phone': request.form.get('phone'),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        db_put('requestors', req)
        # set session and show explicit registration success page
        session['requestor_id'] = requestor_id
        flash(f'Requestor registered: {requestor_id}', 'success')
        return redirect(url_for('registration_success', role='requestor', entity_id=requestor_id))
    return render_template('requestor_register.html')


# Update donor profile
@app.route('/donor/update/<donor_id>', methods=['POST'])
def donor_update(donor_id):
    donor = db_get('donors', {'donor_id': donor_id})
    if not donor:
        flash('Donor not found', 'error')
        return redirect(url_for('donor_dashboard'))
    # update allowed fields
    for field in ['phone', 'address', 'city', 'state', 'pincode', 'emergency_contact', 'preferred_contact_time']:
        if field in request.form:
            donor[field] = request.form.get(field)
    db_put('donors', donor)
    flash('Profile updated', 'success')
    return redirect(url_for('donor_dashboard'))


# Donor confirms a donation for an assignment
@app.route('/donor/confirm/<assignment_id>', methods=['POST'])
def donor_confirm_donation(assignment_id):
    # Minimal implementation: mark assignment as fulfilled and record a donation
    assignment = None
    for a in db_scan('assignments'):
        if a.get('assignment_id') == assignment_id:
            assignment = a
            break
    if not assignment:
        flash('Assignment not found', 'error')
        return redirect(url_for('donor_dashboard'))
    units = int(request.form.get('units_donated', 0))
    current_time = datetime.now().strftime('%Y-%m-%d')
    donation = {
        'donation_id': generate_id('DN'),
        'donor_id': assignment.get('donor_id'),
        'donor_name': assignment.get('donor_name', ''),
        'blood_group': assignment.get('blood_group', ''),
        'units': units,
        'donation_date': current_time,
        'donation_center': request.form.get('donation_center', '')
    }
    db_put('donations', donation)
    # Persist donations
    _save_json_file('donations.json', list(donations_db.values()))

    # update donor record (total donations, last donation date)
    donor = db_get('donors', {'donor_id': donation.get('donor_id')})
    if donor:
        donor['total_donations'] = int(donor.get('total_donations', 0)) + int(units)
        donor['last_donation'] = donation.get('donation_date')
        db_put('donors', donor)
        _save_json_file('donors.json', list(donors_db.values()))

    # update inventory: add units to matching blood group and track donor
    inv_items = db_scan('inventory')
    found = False
    for item in inv_items:
        bg = item.get('blood_group') or item.get('group')
        if bg and bg == donation.get('blood_group'):
            cur = int(item.get('units', 0))
            item['units'] = cur + int(units)
            item['donation_date'] = current_time
            donors_list = item.get('donors') or []
            if donation.get('donor_id') not in donors_list:
                donors_list.append(donation.get('donor_id'))
            item['donors'] = donors_list
            db_put('inventory', item)
            _save_json_file('inventory.json', list(inventory_db.values()))
            found = True
            break
    if not found:
        new_item = {
            'inventory_id': generate_id('INV'),
            'blood_group': donation.get('blood_group'),
            'units': int(units),
            'donors': [donation.get('donor_id')],
            'donation_date': current_time
        }
        db_put('inventory', new_item)
        _save_json_file('inventory.json', list(inventory_db.values()))

    assignment['status'] = 'completed'
    db_put('assignments', assignment)
    _save_json_file('assignments.json', list(assignments_db.values()))

    # Automatically update request fulfillment
    req = db_get('requests', {'request_id': assignment.get('request_id')})
    if req:
        req['fulfilled_units'] = req.get('fulfilled_units', 0) + units
        if req['fulfilled_units'] >= req.get('units_needed', 0):
            req['status'] = 'fulfilled'
        else:
            req['status'] = 'partial'
        db_put('requests', req)
        _save_json_file('blood_requests.json', list(blood_requests_db.values()))

    flash('Donation confirmed. Request status updated automatically.', 'success')
    return redirect(url_for('donor_dashboard'))


# Donor accepts a request
@app.route('/donor/accept/<donor_id>/<request_id>', methods=['POST'])
def donor_accept_request(donor_id, request_id):
    # Verify donor and request exist
    donor = db_get('donors', {'donor_id': donor_id})
    req = db_get('requests', {'request_id': request_id})
    
    if not donor:
        flash('Donor not found', 'error')
        return redirect(url_for('donor_dashboard'))
    if not req:
        flash('Request not found', 'error')
        return redirect(url_for('donor_dashboard'))
    
    # create assignment
    units_offered = int(request.form.get('units_offered', 1))
    assignment_id = generate_id('ASGN')
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    assignment = {
        'assignment_id': assignment_id,
        'donor_id': donor_id,
        'donor_name': donor.get('name'),
        'blood_group': donor.get('blood_group'),
        'request_id': request_id,
        'units_offered': units_offered,
        'status': 'accepted',
        'created_at': current_time
    }
    db_put('assignments', assignment)
    _save_json_file('assignments.json', list(assignments_db.values()))
    flash(f'Request accepted! Assignment {assignment_id} created.', 'success')
    return redirect(url_for('donor_dashboard'))


# Search donors
@app.route('/search-donors', methods=['GET', 'POST'])
def search_donors():
    search_performed = False
    results = []
    
    if request.method == 'POST':
        bg = request.form.get('blood_group', '')
        location = request.form.get('location', '')
        search_performed = True
        
        # Search donors by blood group and location
        all_donors = db_scan('donors')
        for donor in all_donors:
            bg_match = not bg or donor.get('blood_group') == bg
            location_match = not location or location.lower() in str(donor.get('city', '')).lower() or location.lower() in str(donor.get('state', '')).lower()
            if bg_match and location_match and donor.get('status') == 'active':
                results.append(donor)
    else:
        # GET request - show all available donors by default
        all_donors = db_scan('donors')
        results = [d for d in all_donors if d.get('status') == 'active']
        
        # If specific query params provided, filter results
        q = request.args.get('q', '')
        bg = request.args.get('blood_group')
        if q or bg:
            search_performed = True
            results = get_compatible_donors(bg or '', q)
    
    return render_template('search_donors.html', results=results, search_performed=search_performed)


# Blood inventory view
@app.route('/inventory')
def blood_inventory_view():
    items = db_scan('inventory')
    # Build inventory mapping expected by template (keys = blood group)
    inventory_map = {}
    for item in items:
        bg = item.get('blood_group') or item.get('group') or 'Unknown'
        units = int(item.get('units', 0))
        donors = item.get('donors') or []
        inventory_map[bg] = {
            'units': units,
            'donors': donors
        }

    # Compute stats used by the template
    requests_list = db_scan('requests')
    # ensure all blood groups present
    BLOOD_GROUPS = sorted(set(list(BLOOD_COMPATIBILITY.keys()) + list(RECEIVE_COMPATIBILITY.keys())))
    for bg in BLOOD_GROUPS:
        inventory_map.setdefault(bg, {'units': 0, 'donors': []})

    stats = {
        'total_donors': len(db_scan('donors')),
        'total_requests': len(requests_list),
        'fulfilled_requests': sum(1 for r in requests_list if r.get('status') == 'fulfilled'),
        'total_units': sum(int(i.get('units', 0)) for i in items),
        'critical_groups': [bg for bg, v in inventory_map.items() if v['units'] < 20],
        'inventory': inventory_map
    }

    # Get recent donation transactions (last 20)
    donation_transactions = sorted(db_scan('donations'), key=lambda x: x.get('donation_date') or '', reverse=True)[:20]
    return render_template('blood_inventory.html', inventory=inventory_map, stats=stats, donation_transactions=donation_transactions)


# Admin dashboard
@app.route('/admin')
def admin_dashboard():
    donors = db_scan('donors')
    requests_list = db_scan('requests')
    donations = db_scan('donations')
    inventory_items = db_scan('inventory')
    registrations = sorted(db_scan('donor_registrations'), key=lambda x: x.get('registered_at') or '', reverse=True)[:10]
    recent_donations = sorted(donations, key=lambda x: x.get('donation_date') or '', reverse=True)[:10]
    # build inventory map
    inventory_map = {}
    for item in inventory_items:
        bg = item.get('blood_group') or item.get('group') or 'Unknown'
        inventory_map[bg] = {'units': int(item.get('units', 0))}

    stats = {
        'total_donors': len(donors),
        'total_requestors': len(db_scan('requestors')),
        'total_requests': len(requests_list),
        'active_requests': sum(1 for r in requests_list if r.get('status') in ['pending', 'partial']),
        'fulfilled_requests': sum(1 for r in requests_list if r.get('status') == 'fulfilled'),
        'total_units': sum(int(i.get('units', 0)) for i in inventory_items),
        'inventory': inventory_map
    }
    return render_template('admin_dashboard.html', stats=stats, donors=donors, requests=requests_list, donations=donations, registrations=registrations, recent_donations=recent_donations)


@app.route('/about')
def about():
    return render_template('about.html')


# Registration success page
@app.route('/registration-success/<role>/<entity_id>')
def registration_success(role, entity_id):
    return render_template('registration_success.html', role=role, entity_id=entity_id)


# Request submission success
@app.route('/request-success/<request_id>')
def request_success(request_id):
    return render_template('request_success.html', request_id=request_id)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
