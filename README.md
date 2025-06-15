# CPU Process Monitor

A Python-based CPU process monitoring tool that helps you track and manage system processes, with the ability to identify and terminate processes that are consuming high CPU resources.

## Features

- Real-time monitoring of CPU usage per process
- Memory usage tracking
- Process owner (username) identification
- High CPU usage alerts (default threshold: 70%)
- Ability to terminate processes
- Logging of high CPU usage events and process terminations
- Top 15 processes sorted by CPU usage
- Interactive command interface

## Requirements

- Python 3.6 or higher
- psutil
- prettytable

## Installation

1. Clone or download this repository
2. Install the required packages:
```bash
pip install -r requirements.txt
```

## Usage

1. Run the script:
```bash
python cpu_monitor.py
```

2. The monitor will display:
   - Current system CPU usage
   - Table of top 15 processes sorted by CPU usage
   - Process details including name, PID, CPU%, Memory%, User, and Status

3. Available commands:
   - `k <pid>`: Kill a process by its PID (e.g., `k 1234`)
   - `q`: Quit the monitor

4. Logs are saved to `cpu_monitor.log` in the same directory

## Notes

- Processes using more CPU than the threshold (default 70%) will be marked as "HIGH" in the Status column
- The display updates every 2 seconds
- Some processes may show as "Access Denied" due to system permissions
- Run with administrator/root privileges for full access to all processes 