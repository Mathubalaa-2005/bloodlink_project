# Real-Time Updates & Blood Type Compatibility Guide
## BloodSync Blood Bank Management System

---

## Overview

This guide explains the real-time inventory and dashboard updates that happen automatically when donors register, along with the blood type compatibility system.

---

## 1. Real-Time Updates When Donor Registers

### What Happens Automatically:

When a **new donor registers**, the system now:

1. **Creates Donor Record** ✓
   - Stores complete donor information (name, email, phone, blood group, location, etc.)
   - Assigns unique Donor ID
   - Records registration timestamp

2. **Updates Inventory Immediately** ✓
   - Adds donor to the blood group inventory list
   - Increments donor count for that blood group
   - Saves to persistent JSON storage

3. **Updates Dashboard Statistics** ✓
   - Total donor count increases
   - Blood group donor count updates
   - Inventory status recalculates

4. **Triggers Frontend Auto-Refresh** ✓
   - Dashboard fetches latest statistics every 10 seconds
   - Inventory page updates unit counts and donor lists
   - Live status badges (Critical/Low/Adequate) update in real-time

### API Endpoints for Real-Time Data:

#### `/api/inventory/real-time` (GET)
Returns complete inventory with donor information and compatibility data.

**Response:**
```json
{
  "success": true,
  "timestamp": "2026-02-06T15:30:45.123456",
  "inventory": {
    "A+": {
      "units": 50,
      "donor_count": 3,
      "donor_ids": ["DON-xxxxx", "DON-yyyyy"],
      "can_donate_to": ["A+", "AB+"],
      "can_receive_from": ["A+", "A-", "O+", "O-"],
      "status": "adequate"
    },
    "B-": {
      "units": 15,
      "donor_count": 1,
      "donor_ids": ["DON-zzzzz"],
      "can_donate_to": ["B+", "B-", "AB+", "AB-"],
      "can_receive_from": ["B-", "O-"],
      "status": "critical"
    }
  },
  "total_units": 295,
  "total_donors": 12,
  "critical_groups": ["B-", "AB-", "A-"]
}
```

#### `/api/dashboard/stats` (GET)
Returns dashboard statistics with inventory breakdown.

**Response:**
```json
{
  "success": true,
  "timestamp": "2026-02-06T15:30:45.123456",
  "stats": {
    "total_donors": 12,
    "total_requestors": 5,
    "total_requests": 3,
    "active_requests": 1,
    "fulfilled_requests": 2,
    "total_units": 295,
    "critical_groups": ["B-", "AB-"]
  },
  "inventory_breakdown": {
    "A+": {
      "units": 50,
      "donors": 3,
      "status": "adequate"
    },
    "O-": {
      "units": 40,
      "donors": 2,
      "status": "adequate"
    }
  }
}
```

#### `/api/inventory/update-donor/<donor_id>` (GET)
Manually trigger inventory update for a specific donor.

---

## 2. Blood Type Compatibility System

### Compatibility Matrix:

The system uses two compatibility matrices:

#### **A. BLOOD_COMPATIBILITY** (What Each Type Can Donate To)
```
A+   → Can donate to: A+, AB+
A-   → Can donate to: A+, A-, AB+, AB-
B+   → Can donate to: B+, AB+
B-   → Can donate to: B+, B-, AB+, AB-
AB+  → Can donate to: AB+
AB-  → Can donate to: AB+, AB-
O+   → Can donate to: O+, A+, B+, AB+ (Universal Donor)
O-   → Can donate to: ALL BLOOD TYPES (Most Universal)
```

#### **B. RECEIVE_COMPATIBILITY** (What Each Type Can Receive From)
```
A+   → Can receive from: A+, A-, O+, O-
A-   → Can receive from: A-, O-
B+   → Can receive from: B+, B-, O+, O-
B-   → Can receive from: B-, O-
AB+  → Can receive from: ALL BLOOD TYPES (Universal Recipient)
AB-  → Can receive from: A-, B-, AB-, O-
O+   → Can receive from: O+, O-
O-   → Can receive from: O-
```

### How Compatibility is Used:

1. **When Processing Blood Requests**
   - System matches requestor's blood type with compatible donors
   - Only searches donors with compatible blood groups
   - Prioritizes by donation eligibility (56-day gap)

2. **In Donor Search**
   - Filters donors based on recipient blood type
   - Shows compatibility information on search results
   - Colors indicate compatibility (Green = compatible, Red = incompatible)

3. **On Inventory Display**
   - Shows what each blood group can donate to
   - Shows what blood groups can donate to this type
   - Alerts for critical shortages in compatible blood types

### Real-Time Compatibility Updates:

When a new donor registers with specific blood type:
- Automatically added to donor lists for compatible requests
- Dashboard updates showing increased donor availability
- Inventory status may change from "Critical" to "Low" or "Adequate"

---

## 3. Dashboard Updates

### What Updates in Real-Time:

#### On Inventory Page (`/blood-inventory`):
- **Total Units Available** - Updates when inventory changes
- **Registered Donors** - Updates when new donor registers
- **Total Requests** - Updates when new request is created
- **Critical Blood Groups** - Updates dynamically

#### On Admin Dashboard (`/dashboard`):
- **Total Donors** - Live count of all registered donors
- **Total Requests** - Live count of blood requests
- **Fulfilled Requests** - Count of completed requests
- **Total Units** - Sum of all available units
- **Inventory Breakdown** - Unit and donor count per blood type

### Update Frequency:

- **Initial Load**: Data fetched when page loads
- **Auto-Refresh**: Every 10 seconds (configurable)
- **On Trigger**: Manually refresh via button click
- **On Registration**: Immediate update after donor registers

---

## 4. Implementation Details

### Backend Changes (app.py):

1. **Enhanced `donor_register()` Route**
   - Adds logging for registration timestamp
   - Logs total donor count per blood group
   - Ensures donor is added to inventory immediately

2. **New API Endpoints**
   - `/api/inventory/real-time` - Real-time inventory data
   - `/api/dashboard/stats` - Dashboard statistics
   - `/api/inventory/update-donor/<donor_id>` - Trigger inventory update

3. **Enhanced `get_statistics()` Function**
   - Returns detailed inventory breakdown
   - Includes critical blood group detection
   - Provides timestamps for tracking

### Frontend Changes (main.js):

1. **Real-Time Fetch Functions**
   - `fetchRealtimeInventory()` - Gets latest inventory data
   - `fetchDashboardStats()` - Gets dashboard statistics
   - `initRealtimeUpdates()` - Sets up auto-refresh

2. **DOM Update Functions**
   - `updateInventoryDisplay()` - Updates inventory cards
   - `updateDashboardStats()` - Updates stat cards
   - `updateInventoryBreakdown()` - Updates data tables

3. **Auto-Refresh Mechanism**
   - 10-second interval for inventory page
   - 10-second interval for dashboard page
   - Automatic cleanup on page exit

### Template Changes:

1. **blood_inventory.html**
   - Added `data-page="inventory"` for page detection
   - Added `data-blood-group` attributes for cards
   - Added `data-stat` attributes for statistics
   - Classes for units, donors, and status updates

2. **admin_dashboard.html**
   - Added `data-page="dashboard"` for page detection
   - Added `data-dashboard-stat` attributes for statistics
   - Real-time stat card updates

---

## 5. How to Use

### For Blood Donors:

1. **Register**
   - Fill out registration form with blood type
   - Submit to register
   - Automatically added to inventory system

2. **See Updates**
   - Go to inventory page
   - See your blood type updated with new donor count
   - Refresh every 10 seconds automatically

### For Hospital/Requestors:

1. **Request Blood**
   - Select required blood type
   - System shows compatible donors automatically
   - See availability in real-time

2. **Check Inventory**
   - Inventory page updates every 10 seconds
   - Critical alerts update in real-time
   - See donor count for each blood type

### For Admin:

1. **Monitor System**
   - Dashboard updates every 10 seconds
   - See total donors, requests, fulfilled requests
   - Track critical blood groups
   - Monitor inventory by blood type

---

## 6. Configuration

### Auto-Refresh Interval:

To change the update frequency, modify `main.js` line (in `initRealtimeUpdates()`):

```javascript
setInterval(() => {
    if (isInventoryPage) fetchRealtimeInventory();
    if (isDashboardPage) fetchDashboardStats();
}, 10000);  // Change 10000 to desired milliseconds
```

**Examples:**
- `5000` = 5 second refresh
- `10000` = 10 second refresh
- `30000` = 30 second refresh
- `60000` = 1 minute refresh

---

## 7. Benefits

✓ **Instant Updates** - Inventory updates immediately when donor registers
✓ **Real-Time Availability** - Hospitals see current available donors
✓ **Optimized Matching** - Blood compatibility ensures safe transfusions
✓ **Critical Alerts** - System alerts when blood types reach critical levels
✓ **Better Planning** - Admin can track trends and plan recruitment
✓ **Live Dashboard** - Monitor entire system in real-time
✓ **Reduced Response Time** - Faster blood request fulfillment

---

## 8. Testing Real-Time Updates

### Test Scenario 1: New Donor Registration

1. Open two browser windows:
   - Window 1: Go to `/blood-inventory`
   - Window 2: Go to `/donor/register`

2. In Window 2, register a new donor with blood type O+

3. In Window 1, watch the:
   - O+ donor count increase
   - Dashboard total donors increase
   - Status badges update

### Test Scenario 2: Inventory Check

1. Register multiple donors with same blood type
2. Watch inventory page update automatically
3. Try donating units to inventory
4. Watch total units change in real-time

### Test Scenario 3: Blood Request Fulfillment

1. Create a blood request
2. System shows compatible donors automatically
3. Fulfill request with donor blood
4. Inventory units decrease in real-time
5. Request status updates automatically

---

## 9. Troubleshooting

### Updates Not Appearing?

1. **Check API Endpoints:**
   ```bash
   curl http://localhost:5000/api/inventory/real-time
   curl http://localhost:5000/api/dashboard/stats
   ```

2. **Check Browser Console:**
   - Open DevTools (F12)
   - Check for JavaScript errors
   - Verify fetch requests in Network tab

3. **Check Data Attributes:**
   - Ensure templates have `data-page` attributes
   - Ensure elements have `data-stat` or `data-dashboard-stat`
   - Check class names match in JavaScript

### Refresh Not Working?

1. Ensure `initRealtimeUpdates()` is being called
2. Check that page has correct `data-page` attribute
3. Verify interval is set correctly (not 0)
4. Check browser DevTools > Network tab for API calls

---

## 10. Future Enhancements

- [ ] WebSocket connection for instant updates (no polling)
- [ ] Push notifications for critical blood shortages
- [ ] SMS alerts for donors
- [ ] Mobile app real-time sync
- [ ] Advanced analytics and reporting
- [ ] Predictive inventory management

---

**Last Updated:** February 6, 2026
**Version:** 2.1 - Real-Time Updates & Enhanced Compatibility
