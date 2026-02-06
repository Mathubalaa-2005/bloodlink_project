"""
BloodSync - Blood Bank Management System
Flask Backend Application
Connects Blood Donors with Requestors
Version 2.0 - Enhanced with Request-Donor Matching Flow
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
import uuid
import json
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = 'bloodsync-secret-key-2024-enhanced'

# ============== DATA STORAGE (Persistent JSON Files) ==============

# Create data directory if it doesn't exist
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# File paths for persistent storage
DONORS_FILE = os.path.join(DATA_DIR, 'donors.json')
REQUESTORS_FILE = os.path.join(DATA_DIR, 'requestors.json')
BLOOD_REQUESTS_FILE = os.path.join(DATA_DIR, 'blood_requests.json')
DONATIONS_FILE = os.path.join(DATA_DIR, 'donations.json')
ASSIGNMENTS_FILE = os.path.join(DATA_DIR, 'assignments.json')
INVENTORY_FILE = os.path.join(DATA_DIR, 'inventory.json')

def load_json_file(file_path, default_value=None):
    """Load data from JSON file"""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
    return default_value if default_value is not None else {}

def save_json_file(file_path, data):
    """Save data to JSON file"""
    try:
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving {file_path}: {e}")
        return False

# Load data from JSON files on startup
donors_db = load_json_file(DONORS_FILE, {})
requestors_db = load_json_file(REQUESTORS_FILE, {})
blood_requests_db = load_json_file(BLOOD_REQUESTS_FILE, {})
donations_db = load_json_file(DONATIONS_FILE, {})
donor_request_assignments = load_json_file(ASSIGNMENTS_FILE, {})

# Blood inventory by blood group - with persistent storage
DEFAULT_INVENTORY = {
    'A+': {'units': 50, 'donors': []},
    'A-': {'units': 30, 'donors': []},
    'B+': {'units': 45, 'donors': []},
    'B-': {'units': 25, 'donors': []},
    'AB+': {'units': 20, 'donors': []},
    'AB-': {'units': 15, 'donors': []},
    'O+': {'units': 60, 'donors': []},
    'O-': {'units': 40, 'donors': []}
}
blood_inventory = load_json_file(INVENTORY_FILE, DEFAULT_INVENTORY)

# ============== BLOOD COMPATIBILITY MATRIX ==============
# Who can DONATE TO whom (Donor Blood Group -> Recipient Blood Groups)
BLOOD_COMPATIBILITY = {
    'A+': ['A+', 'AB+'],
    'A-': ['A+', 'A-', 'AB+', 'AB-'],
    'B+': ['B+', 'AB+'],
    'B-': ['B+', 'B-', 'AB+', 'AB-'],
    'AB+': ['AB+'],
    'AB-': ['AB+', 'AB-'],
    'O+': ['O+', 'A+', 'B+', 'AB+'],
    'O-': ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-']  # Universal donor
}

# Who can RECEIVE FROM whom (Recipient Blood Group -> Donor Blood Groups)
RECEIVE_COMPATIBILITY = {
    'A+': ['A+', 'A-', 'O+', 'O-'],
    'A-': ['A-', 'O-'],
    'B+': ['B+', 'B-', 'O+', 'O-'],
    'B-': ['B-', 'O-'],
    'AB+': ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'],  # Universal recipient
    'AB-': ['A-', 'B-', 'AB-', 'O-'],
    'O+': ['O+', 'O-'],
    'O-': ['O-']
}

# ============== HELPER FUNCTIONS ==============

def generate_donor_id():
    """Generate unique donor ID"""
    return f"DON-{uuid.uuid4().hex[:8].upper()}"

def generate_requestor_id():
    """Generate unique requestor ID"""
    return f"REQ-{uuid.uuid4().hex[:8].upper()}"

def generate_request_id():
    """Generate unique blood request ID"""
    return f"BR-{uuid.uuid4().hex[:8].upper()}"

def generate_donation_id():
    """Generate unique donation ID"""
    return f"DN-{uuid.uuid4().hex[:8].upper()}"

def generate_assignment_id():
    """Generate unique assignment ID"""
    return f"ASGN-{uuid.uuid4().hex[:8].upper()}"

def get_compatible_donor_blood_groups(recipient_blood_group):
    """
    Get list of donor blood groups that can donate to recipient
    Example: For A+ recipient, returns ['A+', 'A-', 'O+', 'O-']
    """
    return RECEIVE_COMPATIBILITY.get(recipient_blood_group, [])

def get_compatible_donors(recipient_blood_group, location=None):
    """
    Find compatible donors who can donate to recipient's blood group
    Returns list of compatible donors
    """
    compatible_blood_groups = get_compatible_donor_blood_groups(recipient_blood_group)
    compatible_donors = []
    
    for donor_id, donor in donors_db.items():
        if donor['blood_group'] in compatible_blood_groups:
            if donor['available'] and donor['status'] == 'active':
                # Check location if specified
                if location:
                    if (location.lower() in donor.get('city', '').lower() or 
                        location.lower() in donor.get('state', '').lower()):
                        compatible_donors.append(donor)
                else:
                    compatible_donors.append(donor)
    
    # Sort by last donation date (most recent first)
    # Use a fallback string when value is None to avoid TypeError during comparison
    compatible_donors.sort(key=lambda x: (x.get('last_donation') or '1900-01-01'), reverse=True)
    return compatible_donors

def can_donate(last_donation_date):
    """Check if donor can donate (56 days gap required)"""
    if not last_donation_date:
        return True
    try:
        last = datetime.strptime(last_donation_date, '%Y-%m-%d')
        return (datetime.now() - last).days >= 56
    except:
        return True

def calculate_donor_eligibility(donor):
    """Calculate donor eligibility score"""
    score = 100
    
    # Age factor
    age = donor.get('age', 0)
    if 25 <= age <= 45:
        score += 10
    elif age < 18 or age > 65:
        score -= 50
    
    # Availability
    if not donor.get('available', True):
        score -= 100
    
    # Last donation recency
    last_donation = donor.get('last_donation')
    if last_donation:
        try:
            days_since = (datetime.now() - datetime.strptime(last_donation, '%Y-%m-%d')).days
            if days_since > 90:
                score += 5
        except:
            pass
    else:
        score += 10  # New donor bonus
    
    # Donation history
    total_donations = donor.get('total_donations', 0)
    score += min(total_donations * 2, 20)
    
    return max(0, min(score, 150))

def get_donor_assigned_requests(donor_id):
    """Get all requests assigned to a donor"""
    assigned = []
    for assignment in donor_request_assignments.values():
        if assignment['donor_id'] == donor_id and assignment['status'] in ['pending', 'accepted']:
            request_data = blood_requests_db.get(assignment['request_id'])
            if request_data:
                assigned.append({
                    **assignment,
                    'request': request_data
                })
    return assigned

def get_request_assigned_donors(request_id):
    """Get all donors assigned to a request"""
    assigned = []
    for assignment in donor_request_assignments.values():
        if assignment['request_id'] == request_id:
            donor_data = donors_db.get(assignment['donor_id'])
            if donor_data:
                assigned.append({
                    **assignment,
                    'donor': donor_data
                })
    return assigned

def get_available_requests_for_donor(donor_id):
    """Get all requests that this donor can fulfill"""
    donor = donors_db.get(donor_id)
    if not donor:
        return []
    
    donor_blood_group = donor['blood_group']
    # Get blood groups this donor can donate to
    can_donate_to = BLOOD_COMPATIBILITY.get(donor_blood_group, [])
    
    available_requests = []
    for request_id, request_data in blood_requests_db.items():
        # Check if request blood group is in the list this donor can donate to
        if request_data['blood_group'] in can_donate_to:
            # Check if request is still pending or partial
            if request_data['status'] in ['pending', 'partial']:
                # Check if this donor is not already assigned
                already_assigned = any(
                    a['donor_id'] == donor_id and a['request_id'] == request_id 
                    for a in donor_request_assignments.values()
                )
                if not already_assigned:
                    # Calculate remaining units needed
                    remaining = request_data['units_needed'] - request_data.get('fulfilled_units', 0)
                    available_requests.append({
                        **request_data,
                        'remaining_units': remaining
                    })
    
    # Sort by urgency and date (guard against missing/None created_at)
    urgency_order = {'critical': 0, 'high': 1, 'normal': 2}
    available_requests.sort(key=lambda x: (urgency_order.get(x.get('urgency'), 2), x.get('created_at') or '1900-01-01'))
    
    return available_requests

def match_blood_request(request_data):
    """
    Blood matching algorithm
    Finds best matching donors for a blood request
    """
    blood_group = request_data['blood_group']
    units_needed = request_data['units_needed']
    location = request_data.get('location', '')
    urgency = request_data.get('urgency', 'normal')
    
    # Get compatible donors
    compatible_donors = get_compatible_donors(blood_group, location)
    
    # Calculate eligibility scores
    scored_donors = []
    for donor in compatible_donors:
        score = calculate_donor_eligibility(donor)
        scored_donors.append({
            **donor,
            'match_score': score,
            'can_donate_now': can_donate(donor.get('last_donation'))
        })
    
    # Sort by match score
    scored_donors.sort(key=lambda x: x['match_score'], reverse=True)
    
    # Check inventory first for exact match
    inventory_available = blood_inventory.get(blood_group, {}).get('units', 0)
    
    # Calculate remaining units needed
    remaining_units = units_needed - request_data.get('fulfilled_units', 0)
    
    return {
        'exact_match_inventory': inventory_available,
        'compatible_donors': scored_donors[:10],  # Top 10 matches
        'total_compatible': len(scored_donors),
        'fulfillable': inventory_available >= remaining_units or len(scored_donors) > 0,
        'remaining_units': remaining_units
    }

def update_inventory(blood_group, units, operation='add'):
    """Update blood inventory"""
    if blood_group in blood_inventory:
        if operation == 'add':
            blood_inventory[blood_group]['units'] += units
        elif operation == 'remove':
            blood_inventory[blood_group]['units'] = max(0, blood_inventory[blood_group]['units'] - units)

def get_statistics():
    """Get dashboard statistics"""
    total_donors = len(donors_db)
    total_requestors = len(requestors_db)
    total_requests = len(blood_requests_db)
    
    active_requests = sum(1 for r in blood_requests_db.values() if r['status'] in ['pending', 'partial'])
    fulfilled_requests = sum(1 for r in blood_requests_db.values() if r['status'] == 'fulfilled')
    
    total_units_available = sum(inv['units'] for inv in blood_inventory.values())
    
    # Critical blood groups (less than 20 units)
    critical_groups = [bg for bg, inv in blood_inventory.items() if inv['units'] < 20]
    
    return {
        'total_donors': total_donors,
        'total_requestors': total_requestors,
        'total_requests': total_requests,
        'active_requests': active_requests,
        'fulfilled_requests': fulfilled_requests,
        'total_units': total_units_available,
        'critical_groups': critical_groups,
        'inventory': blood_inventory
    }

def get_eligible_donors_for_remaining(request_id):
    """Get eligible donors for remaining units of a blood request"""
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        return []
    
    remaining_units = request_data['units_needed'] - request_data.get('fulfilled_units', 0)
    if remaining_units <= 0:
        return []  # Request already fulfilled
    
    required_blood_group = request_data['blood_group']
    eligible_donors = []
    
    # Get all donors with matching blood group
    for donor_id, donor in donors_db.items():
        if donor['blood_group'] != required_blood_group:
            continue  # Wrong blood group
        
        # Check if donor is available
        if not donor.get('available', True) or donor.get('status') != 'active':
            continue
        
        # Check donation eligibility
        can_donate_now = can_donate(donor.get('last_donation'))
        
        # Check if already assigned to this request
        already_assigned = any(
            a['donor_id'] == donor_id and a['request_id'] == request_id 
            for a in donor_request_assignments.values()
        )
        
        eligible_donors.append({
            'donor_id': donor_id,
            'name': donor['name'],
            'phone': donor['phone'],
            'email': donor['email'],
            'last_donation': donor.get('last_donation'),
            'total_donations': donor.get('total_donations', 0),
            'can_donate_now': can_donate_now,
            'is_already_assigned': already_assigned,
            'blood_group': donor['blood_group']
        })
    
    # Sort by donation eligibility and total donations
    eligible_donors.sort(key=lambda x: (not x['can_donate_now'], -x['total_donations']))
    return eligible_donors

def get_matching_donors_for_request(request_id):
    """Get donors who have accepted the request"""
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        return []
    
    matching_donors = []
    for assignment in donor_request_assignments.values():
        if assignment['request_id'] == request_id:
            donor = donors_db.get(assignment['donor_id'])
            if donor:
                matching_donors.append({
                    'assignment_id': assignment['assignment_id'],
                    'donor_id': assignment['donor_id'],
                    'donor_name': donor['name'],
                    'blood_group': donor['blood_group'],
                    'units_offered': assignment.get('units_offered', 0),
                    'status': assignment.get('status', 'pending'),
                    'phone': donor['phone']
                })
    
    return matching_donors

def get_fulfilled_history_for_request(request_id):
    """Get history of donations that fulfilled this request"""
    fulfilled = []
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        return []
    
    for donation in donations_db.values():
        if donation.get('request_id') == request_id and donation.get('status') == 'completed':
            fulfilled.append({
                'donation_id': donation['donation_id'],
                'donor_name': donation.get('donor_name', 'Unknown'),
                'blood_group': donation['blood_group'],
                'units': donation['units'],
                'donation_date': donation.get('donation_date', 'N/A'),
                'hospital_name': donation.get('hospital_name', 'N/A')
            })
    
    return fulfilled

# ============== ROUTES ==============

@app.route('/')
def home():
    """Home page"""
    stats = get_statistics()
    recent_requests = sorted(
        blood_requests_db.values(), 
        key=lambda x: (x.get('created_at') or ''), 
        reverse=True
    )[:5]
    return render_template('index.html', stats=stats, recent_requests=recent_requests)

@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')

# ============== DONOR ROUTES ==============

@app.route('/donor/register', methods=['GET', 'POST'])
def donor_register():
    """Donor registration"""
    if request.method == 'POST':
        donor_id = generate_donor_id()
        
        donor_data = {
            'donor_id': donor_id,
            'name': request.form['name'],
            'email': request.form['email'],
            'phone': request.form['phone'],
            'age': int(request.form['age']),
            'gender': request.form['gender'],
            'blood_group': request.form['blood_group'],
            'weight': float(request.form['weight']),
            'address': request.form['address'],
            'city': request.form['city'],
            'state': request.form['state'],
            'pincode': request.form['pincode'],
            'medical_history': request.form.get('medical_history', 'None'),
            'available': True,
            'status': 'active',
            'total_donations': 0,
            'last_donation': None,
            'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'emergency_contact': request.form.get('emergency_contact', ''),
            'preferred_contact_time': request.form.get('preferred_contact_time', 'Anytime')
        }
        
        # Validate age
        if donor_data['age'] < 18 or donor_data['age'] > 65:
            flash('Donor age must be between 18 and 65 years!', 'error')
            return redirect(url_for('donor_register'))
        
        # Validate weight
        if donor_data['weight'] < 50:
            flash('Donor weight must be at least 50kg!', 'error')
            return redirect(url_for('donor_register'))
        
        donors_db[donor_id] = donor_data
        blood_group = donor_data['blood_group']
        
        # Update inventory donor list - REAL-TIME UPDATE
        if blood_group not in blood_inventory:
            blood_inventory[blood_group] = {'units': 0, 'donors': []}
        
        if donor_id not in blood_inventory[blood_group]['donors']:
            blood_inventory[blood_group]['donors'].append(donor_id)
        
        # SAVE DATA PERSISTENTLY
        save_json_file(DONORS_FILE, donors_db)
        save_json_file(INVENTORY_FILE, blood_inventory)
        
        # Log the registration with timestamp for real-time updates
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{current_time}] New donor registered: {donor_id} ({blood_group})")
        print(f"[{current_time}] Donor count for {blood_group}: {len(blood_inventory[blood_group]['donors'])}")
        
        flash(f'✓ Registration successful! Your Donor ID is: {donor_id}', 'success')
        return redirect(url_for('donor_dashboard', donor_id=donor_id))
    
    return render_template('donor_register.html')

@app.route('/donor/dashboard/<donor_id>')
def donor_dashboard(donor_id):
    """Donor dashboard"""
    donor = donors_db.get(donor_id)
    if not donor:
        flash('Donor not found!', 'error')
        return redirect(url_for('home'))
    
    # Get donation history - ENHANCED for Feature 3
    donation_history = [d for d in donations_db.values() if d['donor_id'] == donor_id]
    # Sort by date (newest first)
    donation_history.sort(key=lambda x: x.get('donation_date', ''), reverse=True)
    
    # Check eligibility
    can_donate_now = can_donate(donor.get('last_donation'))
    
    # Get assigned requests
    assigned_requests = get_donor_assigned_requests(donor_id)
    
    # Get available requests for this donor
    available_requests = get_available_requests_for_donor(donor_id)
    
    return render_template('donor_dashboard.html', donor=donor, 
                          donation_history=donation_history, 
                          can_donate_now=can_donate_now,
                          assigned_requests=assigned_requests,
                          available_requests=available_requests)

@app.route('/donor/login', methods=['GET', 'POST'])
def donor_login():
    """Donor login"""
    if request.method == 'POST':
        donor_id = request.form['donor_id']
        email = request.form['email']
        
        donor = donors_db.get(donor_id)
        if donor and donor['email'] == email:
            session['donor_id'] = donor_id
            flash('Login successful!', 'success')
            return redirect(url_for('donor_dashboard', donor_id=donor_id))
        else:
            flash('Invalid Donor ID or Email!', 'error')
    
    return render_template('donor_login.html')

@app.route('/donor/update/<donor_id>', methods=['POST'])
def donor_update(donor_id):
    """Update donor information"""
    donor = donors_db.get(donor_id)
    if not donor:
        flash('Donor not found!', 'error')
        return redirect(url_for('home'))
    
    donor['phone'] = request.form.get('phone', donor['phone'])
    donor['address'] = request.form.get('address', donor['address'])
    donor['available'] = request.form.get('available') == 'on'
    donor['city'] = request.form.get('city', donor['city'])
    donor['state'] = request.form.get('state', donor['state'])
    
    flash('Profile updated successfully!', 'success')
    return redirect(url_for('donor_dashboard', donor_id=donor_id))

@app.route('/donor/donate/<donor_id>', methods=['POST'])
def record_donation(donor_id):
    """Record a new donation"""
    donor = donors_db.get(donor_id)
    if not donor:
        flash('Donor not found!', 'error')
        return redirect(url_for('home'))
    
    if not can_donate(donor.get('last_donation')):
        flash('You must wait 56 days between donations!', 'error')
        return redirect(url_for('donor_dashboard', donor_id=donor_id))
    
    donation_id = generate_donation_id()
    units = int(request.form.get('units', 1))
    
    donation_data = {
        'donation_id': donation_id,
        'donor_id': donor_id,
        'donor_name': donor['name'],
        'blood_group': donor['blood_group'],
        'units': units,
        'donation_date': datetime.now().strftime('%Y-%m-%d'),
        'donation_center': request.form.get('donation_center', 'Main Center'),
        'notes': request.form.get('notes', '')
    }
    
    donations_db[donation_id] = donation_data
    
    # Update donor record
    donor['last_donation'] = donation_data['donation_date']
    donor['total_donations'] += 1
    
    # Update inventory
    update_inventory(donor['blood_group'], units, 'add')
    
    # SAVE DATA PERSISTENTLY
    save_json_file(DONATIONS_FILE, donations_db)
    save_json_file(DONORS_FILE, donors_db)
    save_json_file(INVENTORY_FILE, blood_inventory)
    
    flash(f'Donation recorded successfully! Donation ID: {donation_id}', 'success')
    return redirect(url_for('donor_dashboard', donor_id=donor_id))

# ============== FEATURE 1: DONATE DIRECTLY TO INVENTORY ==============

@app.route('/donor/donate-to-inventory/<donor_id>', methods=['GET', 'POST'])
def donate_to_inventory(donor_id):
    """Allow donor to donate blood directly to inventory"""
    donor = donors_db.get(donor_id)
    if not donor:
        flash('Donor not found!', 'error')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        # Check eligibility
        if not can_donate(donor.get('last_donation')):
            flash('You must wait 56 days between donations!', 'error')
            return redirect(url_for('donate_to_inventory', donor_id=donor_id))
        
        # Get form data
        blood_group = donor['blood_group']
        units = int(request.form.get('units', 1))
        donation_center = request.form.get('donation_center', 'Main Blood Bank')
        notes = request.form.get('notes', '')
        
        # Validate units
        if units <= 0 or units > 50:
            flash('Units must be between 1 and 50!', 'error')
            return redirect(url_for('donate_to_inventory', donor_id=donor_id))
        
        # Create donation record
        donation_id = generate_donation_id()
        donation_data = {
            'donation_id': donation_id,
            'donor_id': donor_id,
            'donor_name': donor['name'],
            'blood_group': blood_group,
            'units': units,
            'donation_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'donation_center': donation_center,
            'notes': notes,
            'requestor_id': 'inventory',  # Mark as inventory donation
            'patient_name': 'Blood Bank Inventory',
            'hospital_name': donation_center,
            'status': 'completed'
        }
        
        # Add donation
        donations_db[donation_id] = donation_data
        
        # Update donor record
        donor['last_donation'] = datetime.now().strftime('%Y-%m-%d')
        donor['total_donations'] = donor.get('total_donations', 0) + 1
        
        # Update inventory - ADD units
        update_inventory(blood_group, units, 'add')
        
        # Add donor to blood group donors list if not already there
        if donor_id not in blood_inventory[blood_group]['donors']:
            blood_inventory[blood_group]['donors'].append(donor_id)
        
        # SAVE PERSISTENTLY
        save_json_file(DONATIONS_FILE, donations_db)
        save_json_file(DONORS_FILE, donors_db)
        save_json_file(INVENTORY_FILE, blood_inventory)
        
        flash(f'✓ Successfully donated {units} unit(s) of {blood_group} to inventory! Donation ID: {donation_id}', 'success')
        return redirect(url_for('donor_dashboard', donor_id=donor_id))
    
    # GET request - show form
    can_donate_now = can_donate(donor.get('last_donation'))
    return render_template('donor_donate_inventory.html', donor=donor, can_donate_now=can_donate_now)

# ============== NEW: DONOR ACCEPT REQUEST FLOW ==============

@app.route('/donor/accept-request/<donor_id>/<request_id>', methods=['POST'])
def donor_accept_request(donor_id, request_id):
    """Donor accepts a blood request"""
    donor = donors_db.get(donor_id)
    request_data = blood_requests_db.get(request_id)
    
    if not donor or not request_data:
        flash('Invalid donor or request!', 'error')
        return redirect(url_for('home'))
    
    # Create assignment
    assignment_id = generate_assignment_id()
    units_offered = int(request.form.get('units_offered', 1))
    
    assignment_data = {
        'assignment_id': assignment_id,
        'donor_id': donor_id,
        'request_id': request_id,
        'units_offered': units_offered,
        'status': 'accepted',
        'accepted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'donated_at': None,
        'notes': request.form.get('notes', '')
    }
    
    donor_request_assignments[assignment_id] = assignment_data
    
    # SAVE DATA PERSISTENTLY
    save_json_file(ASSIGNMENTS_FILE, donor_request_assignments)
    
    flash(f'You have accepted the request! Assignment ID: {assignment_id}', 'success')
    return redirect(url_for('donor_dashboard', donor_id=donor_id))

@app.route('/donor/confirm-donation/<assignment_id>', methods=['POST'])
def donor_confirm_donation(assignment_id):
    """Donor confirms they have donated for an assigned request"""
    assignment = donor_request_assignments.get(assignment_id)
    if not assignment:
        flash('Assignment not found!', 'error')
        return redirect(url_for('home'))
    
    donor_id = assignment['donor_id']
    request_id = assignment['request_id']
    
    donor = donors_db.get(donor_id)
    request_data = blood_requests_db.get(request_id)
    
    if not donor or not request_data:
        flash('Invalid data!', 'error')
        return redirect(url_for('donor_dashboard', donor_id=donor_id))
    
    units_donated = int(request.form.get('units_donated', assignment['units_offered']))
    
    # Update assignment
    assignment['status'] = 'completed'
    assignment['units_donated'] = units_donated
    assignment['donated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Update request fulfilled units
    request_data['fulfilled_units'] = request_data.get('fulfilled_units', 0) + units_donated
    
    # Update request status
    remaining = request_data['units_needed'] - request_data['fulfilled_units']
    if remaining <= 0:
        request_data['status'] = 'fulfilled'
    else:
        request_data['status'] = 'partial'
    
    # Update blood inventory - CONSUME units from inventory
    blood_group = donor['blood_group']
    if blood_group in blood_inventory:
        blood_inventory[blood_group]['units'] = max(0, blood_inventory[blood_group]['units'] - units_donated)
        request_data['inventory_used'] = request_data.get('inventory_used', 0) + units_donated
    
    # Update donor stats
    donor['last_donation'] = datetime.now().strftime('%Y-%m-%d')
    donor['total_donations'] = donor.get('total_donations', 0) + 1
    
    # Create donation record
    donation_id = generate_donation_id()
    donation_data = {
        'donation_id': donation_id,
        'donor_id': donor_id,
        'donor_name': donor['name'],
        'request_id': request_id,
        'patient_name': request_data['patient_name'],
        'blood_group': donor['blood_group'],
        'units': units_donated,
        'donation_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'donation_center': request.form.get('donation_center', request_data['hospital_name']),
        'notes': f'Donation for request {request_id}',
        'assignment_id': assignment_id,
        'status': 'completed'
    }
    donations_db[donation_id] = donation_data
    
    # SAVE DATA PERSISTENTLY
    save_json_file(DONATIONS_FILE, donations_db)
    save_json_file(DONORS_FILE, donors_db)
    save_json_file(BLOOD_REQUESTS_FILE, blood_requests_db)
    save_json_file(ASSIGNMENTS_FILE, donor_request_assignments)
    save_json_file(INVENTORY_FILE, blood_inventory)
    
    flash(f'Donation confirmed! {units_donated} unit(s) donated. Remaining needed: {max(0, remaining)}', 'success')
    return redirect(url_for('donor_dashboard', donor_id=donor_id))

# ============== FEATURE 3: REQUESTOR CONFIRM DONOR ==============

@app.route('/requestor/confirm-donor/<requestor_id>/<assignment_id>', methods=['POST'])
def requestor_confirm_donor(requestor_id, assignment_id):
    """Requestor confirms acceptance of blood from a donor"""
    assignment = donor_request_assignments.get(assignment_id)
    if not assignment:
        flash('Assignment not found!', 'error')
        return redirect(url_for('home'))
    
    requestor = requestors_db.get(requestor_id)
    request_id = assignment['request_id']
    request_data = blood_requests_db.get(request_id)
    donor_id = assignment['donor_id']
    donor = donors_db.get(donor_id)
    
    if not requestor or not request_data or not donor:
        flash('Invalid data!', 'error')
        return redirect(url_for('requestor_dashboard', requestor_id=requestor_id))
    
    # Update assignment status to confirmed
    assignment['status'] = 'requestor_confirmed'
    assignment['confirmed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # SAVE PERSISTENTLY
    save_json_file(ASSIGNMENTS_FILE, donor_request_assignments)
    
    flash(f'✓ You have confirmed blood reception from {donor["name"]}! They will proceed with donation.', 'success')
    return redirect(url_for('requestor_dashboard', requestor_id=requestor_id))

# ============== REQUESTOR ROUTES ==============

@app.route('/requestor/register', methods=['GET', 'POST'])
def requestor_register():
    """Requestor registration"""
    if request.method == 'POST':
        requestor_id = generate_requestor_id()
        
        requestor_data = {
            'requestor_id': requestor_id,
            'name': request.form['name'],
            'email': request.form['email'],
            'phone': request.form['phone'],
            'organization': request.form.get('organization', 'Individual'),
            'address': request.form['address'],
            'city': request.form['city'],
            'state': request.form['state'],
            'pincode': request.form['pincode'],
            'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_requests': 0
        }
        
        requestors_db[requestor_id] = requestor_data
        
        # SAVE DATA PERSISTENTLY
        save_json_file(REQUESTORS_FILE, requestors_db)
        
        flash(f'Registration successful! Your Requestor ID is: {requestor_id}', 'success')
        return redirect(url_for('requestor_dashboard', requestor_id=requestor_id))
    
    return render_template('requestor_register.html')

@app.route('/requestor/dashboard/<requestor_id>')
def requestor_dashboard(requestor_id):
    """Requestor dashboard"""
    requestor = requestors_db.get(requestor_id)
    if not requestor:
        flash('Requestor not found!', 'error')
        return redirect(url_for('home'))
    
    # Get request history with assigned donors - ENHANCED FOR FEATURES 2, 4, 5
    request_history = []
    for req in blood_requests_db.values():
        if req['requestor_id'] == requestor_id:
            assigned_donors = get_request_assigned_donors(req['request_id'])
            fulfilled_history = get_fulfilled_history_for_request(req['request_id'])
            eligible_donors = get_eligible_donors_for_remaining(req['request_id'])
            
            request_history.append({
                **req,
                'assigned_donors': assigned_donors,
                'fulfilled_history': fulfilled_history,
                'eligible_donors': eligible_donors,
                'remaining_units': req['units_needed'] - req.get('fulfilled_units', 0)
            })
    
    # Sort by date (guard against missing/None created_at)
    request_history.sort(key=lambda x: (x.get('created_at') or ''), reverse=True)
    
    return render_template('requestor_dashboard.html', requestor=requestor, 
                          request_history=request_history)

# ============== FEATURE 2: REQUESTOR TAKE BLOOD FROM INVENTORY ==============

@app.route('/requestor/take-from-inventory/<requestor_id>', methods=['GET', 'POST'])
def take_from_inventory(requestor_id):
    """Allow requestor to take blood from inventory"""
    requestor = requestors_db.get(requestor_id)
    if not requestor:
        flash('Requestor not found!', 'error')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        blood_group = request.form.get('blood_group')
        units_needed = int(request.form.get('units_needed', 1))
        hospital_name = request.form.get('hospital_name', requestor.get('organization', 'Hospital'))
        reason = request.form.get('reason', '')
        required_date = request.form.get('required_date', datetime.now().strftime('%Y-%m-%d'))
        
        # Validate blood group
        if blood_group not in blood_inventory:
            flash('Invalid blood group!', 'error')
            return redirect(url_for('take_from_inventory', requestor_id=requestor_id))
        
        # Validate units
        if units_needed <= 0:
            flash('Units must be greater than 0!', 'error')
            return redirect(url_for('take_from_inventory', requestor_id=requestor_id))
        
        # Check inventory availability
        available_units = blood_inventory[blood_group]['units']
        if available_units < units_needed:
            flash(f'❌ Only {available_units} unit(s) of {blood_group} available! You requested {units_needed} units.', 'error')
            return redirect(url_for('take_from_inventory', requestor_id=requestor_id))
        
        # Create a blood request for inventory withdrawal
        request_id = generate_request_id()
        blood_request_data = {
            'request_id': request_id,
            'requestor_id': requestor_id,
            'patient_name': f'Inventory Request - {requestor.get("organization", "Hospital")}',
            'patient_age': 0,
            'patient_gender': 'N/A',
            'blood_group': blood_group,
            'units_needed': units_needed,
            'fulfilled_units': units_needed,  # Mark as immediately fulfilled
            'remaining_units': 0,
            'hospital_name': hospital_name,
            'hospital_address': requestor.get('address', ''),
            'city': requestor.get('city', ''),
            'state': requestor.get('state', ''),
            'contact_name': requestor.get('name'),
            'contact_phone': requestor.get('phone'),
            'contact_email': requestor.get('email'),
            'urgency': 'normal',
            'required_date': required_date,
            'reason': reason or 'Direct inventory request',
            'status': 'fulfilled',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'type': 'inventory_withdrawal'
        }
        
        # Add to blood requests
        blood_requests_db[request_id] = blood_request_data
        
        # Deduct from inventory
        update_inventory(blood_group, units_needed, 'remove')
        
        # Update requestor stats
        requestor['total_requests'] = requestor.get('total_requests', 0) + 1
        
        # Create a donation record for tracking
        donation_id = generate_donation_id()
        donation_data = {
            'donation_id': donation_id,
            'donor_id': 'INVENTORY',
            'donor_name': 'Blood Bank Inventory',
            'blood_group': blood_group,
            'units': units_needed,
            'request_id': request_id,
            'patient_name': blood_request_data['patient_name'],
            'hospital_name': hospital_name,
            'donation_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'completed',
            'notes': f'Direct withdrawal from inventory. Reason: {reason}'
        }
        donations_db[donation_id] = donation_data
        
        # SAVE PERSISTENTLY
        save_json_file(BLOOD_REQUESTS_FILE, blood_requests_db)
        save_json_file(INVENTORY_FILE, blood_inventory)
        save_json_file(REQUESTORS_FILE, requestors_db)
        save_json_file(DONATIONS_FILE, donations_db)
        
        flash(f'✓ Successfully withdrew {units_needed} unit(s) of {blood_group} from inventory! Request ID: {request_id}', 'success')
        return redirect(url_for('requestor_dashboard', requestor_id=requestor_id))
    
    # GET request - show form
    return render_template('requestor_take_inventory.html', requestor=requestor, inventory=blood_inventory)

@app.route('/requestor/login', methods=['GET', 'POST'])
def requestor_login():
    """Requestor login"""
    if request.method == 'POST':
        requestor_id = request.form['requestor_id']
        email = request.form['email']
        
        requestor = requestors_db.get(requestor_id)
        if requestor and requestor['email'] == email:
            session['requestor_id'] = requestor_id
            flash('Login successful!', 'success')
            return redirect(url_for('requestor_dashboard', requestor_id=requestor_id))
        else:
            flash('Invalid Requestor ID or Email!', 'error')
    
    return render_template('requestor_login.html')

# ============== BLOOD REQUEST ROUTES ==============

@app.route('/request-blood', methods=['GET', 'POST'])
def request_blood():
    """Create blood request"""
    if request.method == 'POST':
        request_id = generate_request_id()
        
        request_data = {
            'request_id': request_id,
            'requestor_id': request.form.get('requestor_id', 'GUEST'),
            'patient_name': request.form['patient_name'],
            'patient_age': int(request.form['patient_age']),
            'patient_gender': request.form['patient_gender'],
            'blood_group': request.form['blood_group'],
            'units_needed': int(request.form['units_needed']),
            'hospital_name': request.form['hospital_name'],
            'hospital_address': request.form['hospital_address'],
            'location': request.form.get('city', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', ''),
            'contact_name': request.form['contact_name'],
            'contact_phone': request.form['contact_phone'],
            'contact_email': request.form.get('contact_email', ''),
            'urgency': request.form.get('urgency', 'normal'),
            'required_date': request.form['required_date'],
            'reason': request.form.get('reason', ''),
            'status': 'pending',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'matched_donors': [],
            'fulfilled_units': 0,
            'inventory_used': 0
        }
        
        blood_requests_db[request_id] = request_data
        
        # Update requestor stats if registered
        requestor_id = request_data['requestor_id']
        if requestor_id in requestors_db:
            requestors_db[requestor_id]['total_requests'] += 1
        
        # Run matching algorithm to find compatible donors
        match_results = match_blood_request(request_data)
        blood_requests_db[request_id]['matched_donors'] = [d['donor_id'] for d in match_results['compatible_donors']]
        
        # SAVE DATA PERSISTENTLY
        save_json_file(BLOOD_REQUESTS_FILE, blood_requests_db)
        save_json_file(REQUESTORS_FILE, requestors_db)
        
        flash(f'Blood request created! Request ID: {request_id}', 'success')
        return redirect(url_for('request_details', request_id=request_id))
    
    return render_template('request_blood.html')

@app.route('/request/<request_id>')
def request_details(request_id):
    """View request details with matched donors"""
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        flash('Request not found!', 'error')
        return redirect(url_for('home'))
    
    # Get fresh match results
    match_results = match_blood_request(request_data)
    
    # Get assigned donors
    assigned_donors = get_request_assigned_donors(request_id)
    
    # Calculate remaining units
    remaining_units = request_data['units_needed'] - request_data.get('fulfilled_units', 0)
    
    return render_template('request_details.html', request=request_data, 
                          match_results=match_results,
                          assigned_donors=assigned_donors,
                          remaining_units=remaining_units)

@app.route('/search-donors', methods=['GET', 'POST'])
def search_donors():
    """Search for donors"""
    results = []
    search_performed = False
    
    if request.method == 'POST':
        blood_group = request.form.get('blood_group', '')
        location = request.form.get('location', '')
        
        search_performed = True
        
        for donor in donors_db.values():
            match = True
            
            if blood_group and donor['blood_group'] != blood_group:
                match = False
            
            if location:
                loc_match = (location.lower() in donor.get('city', '').lower() or 
                           location.lower() in donor.get('state', '').lower() or
                           location.lower() in donor.get('pincode', ''))
                if not loc_match:
                    match = False
            
            if match and donor['available'] and donor['status'] == 'active':
                results.append(donor)
    
    return render_template('search_donors.html', results=results, 
                          search_performed=search_performed)

@app.route('/blood-inventory')
def blood_inventory_view():
    """View blood inventory with transaction history"""
    stats = get_statistics()
    
    # Get recent donation transactions (sorted by date descending)
    donation_transactions = list(donations_db.values())
    donation_transactions.sort(key=lambda x: x.get('donation_date', ''), reverse=True)
    donation_transactions = donation_transactions[:50]  # Show last 50 transactions
    
    return render_template('blood_inventory.html', inventory=blood_inventory, stats=stats, 
                         donation_transactions=donation_transactions)

# ============== NEW: INVENTORY DONATION ROUTE ==============

@app.route('/request/<request_id>/use-inventory', methods=['POST'])
def use_inventory_for_request(request_id):
    """Use blood inventory to fulfill a request"""
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        flash('Request not found!', 'error')
        return redirect(url_for('home'))
    
    blood_group = request_data['blood_group']
    units_from_inventory = int(request.form.get('units_from_inventory', 0))
    
    # Check if inventory has enough
    available = blood_inventory.get(blood_group, {}).get('units', 0)
    
    if units_from_inventory > available:
        flash(f'Not enough inventory! Available: {available} units', 'error')
        return redirect(url_for('request_details', request_id=request_id))
    
    # Update inventory
    update_inventory(blood_group, units_from_inventory, 'remove')
    
    # Update request
    request_data['fulfilled_units'] = request_data.get('fulfilled_units', 0) + units_from_inventory
    request_data['inventory_used'] = request_data.get('inventory_used', 0) + units_from_inventory
    
    # Update status
    remaining = request_data['units_needed'] - request_data['fulfilled_units']
    if remaining <= 0:
        request_data['status'] = 'fulfilled'
        flash(f'Request fully fulfilled using {units_from_inventory} unit(s) from inventory!', 'success')
    else:
        request_data['status'] = 'partial'
        flash(f'{units_from_inventory} unit(s) used from inventory. Remaining needed: {remaining}', 'info')
    
    return redirect(url_for('request_details', request_id=request_id))

# ============== NEW: REQUESTOR CONFIRM DONOR ROUTE ==============

@app.route('/request/<request_id>/confirm-donor/<assignment_id>', methods=['POST'])
def confirm_donor_for_request(request_id, assignment_id):
    """Requestor confirms a donor's offer"""
    request_data = blood_requests_db.get(request_id)
    assignment = donor_request_assignments.get(assignment_id)
    
    if not request_data or not assignment:
        flash('Invalid request or assignment!', 'error')
        return redirect(url_for('home'))
    
    # Update assignment status
    assignment['status'] = 'confirmed_by_requestor'
    assignment['confirmed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    flash('Donor confirmed! Waiting for donor to complete the donation.', 'success')
    return redirect(url_for('request_details', request_id=request_id))

# ============== ADMIN/UTILITY ROUTES ==============

@app.route('/dashboard')
def admin_dashboard():
    """Admin dashboard"""
    stats = get_statistics()
    
    # Get all data for admin view
    all_donors = list(donors_db.values())
    all_requests = sorted(blood_requests_db.values(), 
                         key=lambda x: (x.get('created_at') or ''), reverse=True)
    all_donations = sorted(donations_db.values(),
                          key=lambda x: (x.get('donation_date') or ''), reverse=True)
    all_assignments = list(donor_request_assignments.values())
    
    return render_template('admin_dashboard.html', stats=stats, 
                          donors=all_donors, requests=all_requests,
                          donations=all_donations, assignments=all_assignments)

@app.route('/api/statistics')
def api_statistics():
    """API endpoint for statistics"""
    return jsonify(get_statistics())

@app.route('/api/donors')
def api_donors():
    """API endpoint for donors"""
    return jsonify(list(donors_db.values()))

@app.route('/api/requests')
def api_requests():
    """API endpoint for blood requests"""
    return jsonify(list(blood_requests_db.values()))

@app.route('/api/inventory/real-time')
def api_inventory_realtime():
    """
    Real-time API endpoint for inventory data
    Returns inventory with donor counts and compatibility info
    """
    inventory_data = {}
    for blood_group, inv_data in blood_inventory.items():
        # Get compatible blood groups for donors
        can_donate_to = BLOOD_COMPATIBILITY.get(blood_group, [])
        can_receive_from = RECEIVE_COMPATIBILITY.get(blood_group, [])
        
        inventory_data[blood_group] = {
            'units': inv_data.get('units', 0),
            'donor_count': len(inv_data.get('donors', [])),
            'donor_ids': inv_data.get('donors', []),
            'can_donate_to': can_donate_to,
            'can_receive_from': can_receive_from,
            'status': 'critical' if inv_data.get('units', 0) < 20 else ('low' if inv_data.get('units', 0) < 40 else 'adequate')
        }
    
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'inventory': inventory_data,
        'total_units': sum(inv['units'] for inv in blood_inventory.values()),
        'total_donors': len(donors_db),
        'critical_groups': [bg for bg, inv in blood_inventory.items() if inv.get('units', 0) < 20]
    })

@app.route('/api/dashboard/stats')
def api_dashboard_stats():
    """
    Real-time API endpoint for dashboard statistics
    Updates whenever data changes
    """
    stats = get_statistics()
    
    # Add inventory breakdown by blood group
    inventory_breakdown = {}
    for blood_group, inv_data in blood_inventory.items():
        inventory_breakdown[blood_group] = {
            'units': inv_data.get('units', 0),
            'donors': len(inv_data.get('donors', [])),
            'status': 'critical' if inv_data.get('units', 0) < 20 else ('low' if inv_data.get('units', 0) < 40 else 'adequate')
        }
    
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'stats': stats,
        'inventory_breakdown': inventory_breakdown
    })

@app.route('/api/inventory/update-donor/<donor_id>')
def api_update_inventory_for_donor(donor_id):
    """
    API endpoint to update inventory when a new donor registers
    Called automatically after donor registration
    """
    donor = donors_db.get(donor_id)
    if not donor:
        return jsonify({'success': False, 'message': 'Donor not found'}), 404
    
    blood_group = donor.get('blood_group')
    # Ensure donor is in the inventory list
    if donor_id not in blood_inventory[blood_group]['donors']:
        blood_inventory[blood_group]['donors'].append(donor_id)
        save_json_file(INVENTORY_FILE, blood_inventory)
    
    return jsonify({
        'success': True,
        'message': f'Donor {donor_id} added to {blood_group} inventory',
        'blood_group': blood_group,
        'donor_count': len(blood_inventory[blood_group]['donors']),
        'units': blood_inventory[blood_group].get('units', 0)
    })

@app.route('/request/<request_id>/fulfill', methods=['POST'])
def fulfill_request(request_id):
    """Mark request as fulfilled (legacy route)"""
    request_data = blood_requests_db.get(request_id)
    if not request_data:
        flash('Request not found!', 'error')
        return redirect(url_for('home'))
    
    units_fulfilled = int(request.form.get('units_fulfilled', 0))
    
    request_data['fulfilled_units'] = request_data.get('fulfilled_units', 0) + units_fulfilled
    
    if request_data['fulfilled_units'] >= request_data['units_needed']:
        request_data['status'] = 'fulfilled'
        flash('Request fully fulfilled!', 'success')
    else:
        request_data['status'] = 'partial'
        remaining = request_data['units_needed'] - request_data['fulfilled_units']
        flash(f'Partially fulfilled! {remaining} units still needed.', 'info')
    
    # Update inventory
    update_inventory(request_data['blood_group'], units_fulfilled, 'remove')
    
    return redirect(url_for('request_details', request_id=request_id))

@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('home'))

# ============== ERROR HANDLERS ==============

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

# ============== INITIALIZE SAMPLE DATA ==============

def init_sample_data():
    """Initialize sample data for testing - only if not already loaded from files"""
    # Only initialize if databases are empty (no data loaded from files)
    if donors_db or requestors_db or blood_requests_db:
        return  # Data already exists, don't reinitialize
    sample_donors = [
        {
            'donor_id': 'DON-A1B2C3D4',
            'name': 'Rahul Sharma',
            'email': 'rahul@example.com',
            'phone': '9876543210',
            'age': 28,
            'gender': 'Male',
            'blood_group': 'O+',
            'weight': 70,
            'address': '123 Main Street',
            'city': 'Mumbai',
            'state': 'Maharashtra',
            'pincode': '400001',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 5,
            'last_donation': '2024-12-01',
            'registered_at': '2024-01-15 10:30:00',
            'emergency_contact': '9876543211',
            'preferred_contact_time': 'Evening'
        },
        {
            'donor_id': 'DON-E5F6G7H8',
            'name': 'Priya Patel',
            'email': 'priya@example.com',
            'phone': '8765432109',
            'age': 32,
            'gender': 'Female',
            'blood_group': 'A+',
            'weight': 58,
            'address': '456 Park Avenue',
            'city': 'Delhi',
            'state': 'Delhi',
            'pincode': '110001',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 3,
            'last_donation': '2025-01-10',
            'registered_at': '2024-03-20 14:15:00',
            'emergency_contact': '8765432110',
            'preferred_contact_time': 'Morning'
        },
        {
            'donor_id': 'DON-A2B3C4D5',
            'name': 'Anjali Gupta',
            'email': 'anjali@example.com',
            'phone': '7654321098',
            'age': 26,
            'gender': 'Female',
            'blood_group': 'A-',
            'weight': 55,
            'address': '789 Gandhi Road',
            'city': 'Mumbai',
            'state': 'Maharashtra',
            'pincode': '400002',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 2,
            'last_donation': None,
            'registered_at': '2024-06-10 09:00:00',
            'emergency_contact': '7654321099',
            'preferred_contact_time': 'Anytime'
        },
        {
            'donor_id': 'DON-I9J0K1L2',
            'name': 'Amit Kumar',
            'email': 'amit@example.com',
            'phone': '6543210987',
            'age': 25,
            'gender': 'Male',
            'blood_group': 'B-',
            'weight': 72,
            'address': '321 Lake View',
            'city': 'Bangalore',
            'state': 'Karnataka',
            'pincode': '560001',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 2,
            'last_donation': None,
            'registered_at': '2024-06-10 09:00:00',
            'emergency_contact': '6543210988',
            'preferred_contact_time': 'Anytime'
        },
        {
            'donor_id': 'DON-M3N4O5P6',
            'name': 'Sneha Gupta',
            'email': 'sneha@example.com',
            'phone': '5432109876',
            'age': 29,
            'gender': 'Female',
            'blood_group': 'O-',
            'weight': 55,
            'address': '654 Hillside',
            'city': 'Chennai',
            'state': 'Tamil Nadu',
            'pincode': '600001',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 8,
            'last_donation': '2025-01-15',
            'registered_at': '2023-08-05 16:45:00',
            'emergency_contact': '5432109877',
            'preferred_contact_time': 'Afternoon'
        },
        {
            'donor_id': 'DON-Q7R8S9T0',
            'name': 'Vikram Singh',
            'email': 'vikram@example.com',
            'phone': '4321098765',
            'age': 35,
            'gender': 'Male',
            'blood_group': 'AB+',
            'weight': 80,
            'address': '987 River Road',
            'city': 'Pune',
            'state': 'Maharashtra',
            'pincode': '411001',
            'medical_history': 'None',
            'available': True,
            'status': 'active',
            'total_donations': 4,
            'last_donation': '2024-11-20',
            'registered_at': '2024-02-28 11:20:00',
            'emergency_contact': '4321098766',
            'preferred_contact_time': 'Evening'
        }
    ]
    
    for donor in sample_donors:
        donors_db[donor['donor_id']] = donor
        blood_inventory[donor['blood_group']]['donors'].append(donor['donor_id'])
    
    # Sample requestors
    sample_requestors = [
        {
            'requestor_id': 'REQ-X1Y2Z3A4',
            'name': 'Dr. Meera Reddy',
            'email': 'meera@hospital.com',
            'phone': '3210987654',
            'organization': 'City General Hospital',
            'address': 'Hospital Road',
            'city': 'Hyderabad',
            'state': 'Telangana',
            'pincode': '500001',
            'registered_at': '2024-04-10 08:30:00',
            'total_requests': 2
        }
    ]
    
    for requestor in sample_requestors:
        requestors_db[requestor['requestor_id']] = requestor
    
    # Sample blood requests - A+ request that can be fulfilled by A+, A-, O+, O- donors
    sample_requests = [
        {
            'request_id': 'BR-B5C6D7E8',
            'requestor_id': 'REQ-X1Y2Z3A4',
            'patient_name': 'Ramesh Iyer',
            'patient_age': 45,
            'patient_gender': 'Male',
            'blood_group': 'A+',
            'units_needed': 5,
            'hospital_name': 'City General Hospital',
            'hospital_address': 'Hospital Road, Hyderabad',
            'location': 'Hyderabad',
            'city': 'Hyderabad',
            'state': 'Telangana',
            'contact_name': 'Dr. Meera Reddy',
            'contact_phone': '3210987654',
            'contact_email': 'meera@hospital.com',
            'urgency': 'high',
            'required_date': '2025-02-05',
            'reason': 'Surgery',
            'status': 'pending',
            'created_at': '2025-02-01 09:00:00',
            'matched_donors': ['DON-E5F6G7H8', 'DON-A2B3C4D5', 'DON-A1B2C3D4', 'DON-M3N4O5P6'],
            'fulfilled_units': 0,
            'inventory_used': 0
        }
    ]
    
    for req in sample_requests:
        blood_requests_db[req['request_id']] = req
    
    # SAVE SAMPLE DATA PERSISTENTLY
    save_json_file(DONORS_FILE, donors_db)
    save_json_file(REQUESTORS_FILE, requestors_db)
    save_json_file(BLOOD_REQUESTS_FILE, blood_requests_db)
    save_json_file(INVENTORY_FILE, blood_inventory)
    print("Sample data initialized and saved to JSON files")

# Initialize sample data
init_sample_data()

# ============== MAIN ==============

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
