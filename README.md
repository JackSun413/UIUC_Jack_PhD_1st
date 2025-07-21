# LinMot Controller Utilities

This repository contains Python modules for interacting with a LinMot linear motor and BioLogic instrumentation.  The code provides helper classes for device communication, force control, data acquisition and safety monitoring.

## Contents

- **Main.py** – example script showing how the controllers can be combined to automate an experiment.
- **LinMot.py** – wrapper around the LinUDP API used to move the linear motor and apply force limits.
- **Biologic.py** – interface built on the EC‑Lab Development Package for operating BioLogic potentiostats.
- **Phidgets.py** – helper class for reading a Phidgets force sensor.
- **PIDcontroller.py** – simple PID controller implementation.
- **Safety.py** – utilities for checking voltage and force limits during runs.
- **kbio/** – lightweight API bindings extracted from the BioLogic OEM package.

## Quick start

1. Install Python 3 and the required dependencies such as `pythonnet` and `Phidget22`.  The BioLogic DLLs and LinMot DLL must also be available on the system.
2. Edit `Main.py` to point to the correct DLL paths and IP addresses for your hardware.
3. Run the demonstration script:
   ```bash
   python Main.py
   ```

The example performs a sequence of motor operations and electrochemical steps.  Adapt the parameters for your setup.

## Notes

These scripts are provided as a starting point for custom automation.  Additional error handling and calibration may be required for production use.
