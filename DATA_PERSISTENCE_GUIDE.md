# BloodSync Data Persistence Implementation

## Problem Solved
Previously, when you registered a donor or requestor and then exited the website, all registration data would be lost. The data was only stored in memory and would disappear when the application restarted.

## Solution Implemented
The application now uses **JSON file-based persistent storage** to save all data permanently.

## How It Works

### Data Storage
All data is now automatically saved to JSON files in the `data/` folder:
- `donors.json` - All registered donors
- `requestors.json` - All registered requestors  
- `blood_requests.json` - All blood requests
- `donations.json` - All donation records
- `inventory.json` - Blood inventory status
- `assignments.json` - Donor-request assignments

### Automatic Saving
Whenever you:
- **Register a donor** → Saved to `donors.json`
- **Register a requestor** → Saved to `requestors.json`
- **Create a blood request** → Saved to `blood_requests.json`
- **Record a donation** → Saved to all relevant files
- **Accept a request** → Saved to `assignments.json`

### Data Loading
When the application starts:
1. It checks if JSON files exist in the `data/` folder
2. If files exist, it loads all saved data
3. If no files exist, it initializes sample data and saves it

## Key Features
✅ Data persists across application restarts
✅ Login information is preserved
✅ Donation history is maintained
✅ Blood inventory is tracked
✅ All transactions are saved

## File Structure
```
bloodsync/
├── app.py                    (modified with persistence code)
├── data/                     (auto-created)
│   ├── donors.json
│   ├── requestors.json
│   ├── blood_requests.json
│   ├── donations.json
│   ├── assignments.json
│   └── inventory.json
└── ... (other files)
```

## Testing
To verify persistence is working:

1. Start the application
2. Register a new donor or requestor
3. Stop the application (Ctrl+C)
4. Start it again
5. The registered user should still be there!

## Code Changes Made
- Added persistent JSON file I/O functions (`load_json_file`, `save_json_file`)
- Modified registration routes to save data after creating new records
- Updated donation confirmation to save all affected data
- Enhanced initialization to load existing data on startup
- Added automatic save calls throughout the application

## Notes
- The `data/` folder is created automatically on first run
- All JSON files are formatted with 2-space indentation for readability
- Sample data is only initialized on the very first run (if no data files exist)
- All file operations include error handling
