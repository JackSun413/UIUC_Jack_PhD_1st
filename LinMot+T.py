"""Combined data logging system for LinMot force controller and TC-08 temperature sensor."""

from __future__ import annotations

import clr
import time
import csv
import os
import ctypes
import platform
from contextlib import AbstractContextManager
from typing import Optional
from ctypes import byref, c_int16, c_int32, c_float, c_char, POINTER


class LinMotForceController:
    def __init__(self, dll_path, target_ip, target_port="49360", host_ip="192.109.209.100", host_port="41136"):
        clr.AddReference(dll_path) # type: ignore
        import LinUDP # type: ignore
        self.LinUDP = LinUDP
        self.target_ip = target_ip
        self.target_port = target_port
        self.host_ip = host_ip
        self.host_port = host_port
        self.ACI = LinUDP.ACI()
        self.connected = False

    def __enter__(self) -> "LinMotForceController":  # type: ignore[override]
        if not self.connect():
            raise RuntimeError("Failed to connect to LinMot")
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:  # type: ignore[override]
        self.disconnect()
        return False

    def connect(self):
        self.ACI.ClearTargetAddressList()
        self.ACI.SetTargetAddressList(self.target_ip, self.target_port)
        self.ACI.ActivateConnection(self.host_ip, self.host_port)
        self.connected = self.ACI.isConnected(self.target_ip)
        return self.connected

    def _get_state(self):
        return self.ACI.getStateMachineState(self.target_ip)

    def _pretty_state(self, st=None):
        st = st if st is not None else self._get_state()
        try:
            return f"{st} ({int(st)})"
        except Exception:
            return str(st)

    def ensure_drive_ready_for_motion(self, timeout=30):
        """Simple, reliable bring-up: ack errors, call SwitchOn(), wait for OperationEnabled."""
        if self.ACI.isError(self.target_ip):
            print("Acknowledging errors...")
            self.ACI.AckErrors(self.target_ip)
            time.sleep(0.2)

        print(f"Initial drive state: {self._pretty_state()}")

        t0 = time.time()
        if not self.ACI.isHomed(self.target_ip):
            print("Drive is not homed. Calling Homing()...")
            if not self.ACI.Homing(self.target_ip):
                raise RuntimeError("Homing() call failed.")
            print("Waiting for homing to complete...")

        print("Drive is Operation Enabled.")

    def set_force(self, force_n):
        return self.ACI.LMfc_ChangeTargetForce(self.target_ip, float(force_n))

    def stop_force(self):
        return self.set_force(0.0)

    def disconnect(self):
        self.ACI.CloseConnection()
        self.connected = False

    def ensure_force_control_ready(
            self,
            position_mm: float,
            velocity: float = 0.1,
            acceleration: float = 0.2,
            force_limit_n: float = 20.0,
            target_force_n: float = 200.0,
            reset_if_needed: bool = True
    ) -> bool:
        """Ensure the drive is in a valid state for force control."""
        print("Checking force control readiness...")

        if self.ACI.isError(self.target_ip):
            error_txt = self.ACI.LMcf_GetErrorTxt(self.target_ip)
            raise RuntimeError(f"Drive error: {error_txt}")

        if self.ACI.isSpecialMotionActive(self.target_ip):
            print("Drive is already in special motion (likely force control).")
            print(f"Updating target force to {target_force_n} N...")
            self.ACI.LMfc_ChangeTargetForce(self.target_ip, float(target_force_n))
            return True

        if not reset_if_needed:
            print("Force control is not active and reset_if_needed is False — skipping reset.")
            return False

        print("Resetting force control state before reapplying...")
        self.ACI.LMfc_GoToPosRstForceCtrlSetI(
            self.target_ip,
            float(position_mm - 1),
            float(velocity),
            float(acceleration),
            float(acceleration),
        )
        time.sleep(0.2)

        print(f"Starting force control to position {position_mm} mm with {target_force_n} N...")
        success = self.ACI.LMfc_IncrementActPosWithHigherForceCtrlLimitAndTargetForce(
            self.target_ip,
            float(position_mm),
            float(velocity),
            float(acceleration),
            float(force_limit_n),
            float(target_force_n),
        )
        return success

    def get_motor_data(self):
        """Get current motor data (force, current, position)."""
        force = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 2)
        current = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 3)
        position = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 4)

        return {
            'force_raw': force.value,
            'current_raw': current.value,
            'position_raw': position.value
        }

    def move_abs(self,
        position_mm: float,
        max_velocity: float,
        acceleration: float,
        deceleration: float,
    ) -> bool:
        return self.ACI.LMmt_MoveAbs(
            self.target_ip,
            float(position_mm),
            float(max_velocity),
            float(acceleration),
            float(deceleration),
        )


# Direct DLL interface for TC-08
class DirectTC08:
    def __init__(self, dll_path=r"C:\Program Files (x86)\PicoLog\usbtc08.dll"):
        os.add_dll_directory(os.path.dirname(dll_path))
        self.dll = ctypes.WinDLL(dll_path)
        self._setup_function_prototypes()

    def _setup_function_prototypes(self):
        self.dll.usb_tc08_open_unit.restype = c_int16
        self.dll.usb_tc08_open_unit.argtypes = []

        self.dll.usb_tc08_close_unit.restype = c_int16
        self.dll.usb_tc08_close_unit.argtypes = [c_int16]

        self.dll.usb_tc08_set_mains.restype = c_int16
        self.dll.usb_tc08_set_mains.argtypes = [c_int16, c_int16]

        self.dll.usb_tc08_set_channel.restype = c_int16
        self.dll.usb_tc08_set_channel.argtypes = [c_int16, c_int16, c_char]

        self.dll.usb_tc08_get_single.restype = c_int16
        self.dll.usb_tc08_get_single.argtypes = [c_int16, POINTER(c_float), POINTER(c_int16), c_int16]

        self.dll.usb_tc08_get_last_error.restype = c_int16
        self.dll.usb_tc08_get_last_error.argtypes = [c_int16]


class TC08Reader:
    USBTC08_UNITS_C = 0  # Celsius
    USBTC08_UNITS_F = 1  # Fahrenheit
    USBTC08_UNITS_K = 2  # Kelvin
    USBTC08_UNITS_R = 3  # Rankine

    def __init__(self, channels=(1,), tc_type='K', mains_hz=60):
        self.tc08 = DirectTC08()
        self.channels = sorted(set(channels))
        self.tc_type_code = ord(tc_type.upper())
        self.mains_hz = 60 if mains_hz not in (50, 60) else mains_hz
        self.handle = c_int16(0)

    def open(self):
        """Open connection to TC-08 unit"""
        self.handle = c_int16(self.tc08.dll.usb_tc08_open_unit())

        if self.handle.value <= 0:
            error_code = self.tc08.dll.usb_tc08_get_last_error(c_int16(0))
            raise RuntimeError(f"TC-08 not found or driver issue. Error code: {error_code}")

        mains_setting = 1 if self.mains_hz == 60 else 0
        result = self.tc08.dll.usb_tc08_set_mains(self.handle, c_int16(mains_setting))
        if result == 0:
            raise RuntimeError("Failed to set mains frequency")

        self.tc08.dll.usb_tc08_set_channel(self.handle, c_int16(0), c_char(ord(' ')))

        for ch in self.channels:
            result = self.tc08.dll.usb_tc08_set_channel(self.handle, c_int16(ch), c_char(self.tc_type_code))
            if result == 0:
                raise RuntimeError(f"Failed to configure channel {ch}")

        print(f"TC-08 opened successfully with handle {self.handle.value}")

    def close(self):
        """Close connection to TC-08 unit"""
        if self.handle.value > 0:
            self.tc08.dll.usb_tc08_close_unit(self.handle)
            self.handle = c_int16(0)
            print("TC-08 closed")

    def get_single(self, units=USBTC08_UNITS_C):
        """Get single temperature readings from all configured channels"""
        if self.handle.value <= 0:
            raise RuntimeError("TC-08 not open")

        temps = (c_float * 9)()
        overflow = c_int16(0)

        result = self.tc08.dll.usb_tc08_get_single(
            self.handle,
            temps,
            byref(overflow),
            c_int16(units)
        )

        if result == 0:
            error_code = self.tc08.dll.usb_tc08_get_last_error(self.handle)
            raise RuntimeError(f"Failed to get readings. Error code: {error_code}")

        readings = {}
        readings['cold_junction'] = float(temps[0])

        for ch in self.channels:
            readings[f'channel_{ch}'] = float(temps[ch])

        if overflow.value != 0:
            overflow_channels = []
            for i in range(9):
                if overflow.value & (1 << i):
                    overflow_channels.append(i)
            print(f"Warning: Overflow detected on channels: {overflow_channels}")

        return readings

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class CombinedDataLogger:
    """Combined data logger for LinMot and temperature sensors."""

    def __init__(self, linmot_config, temp_config):
        self.linmot_config = linmot_config
        self.temp_config = temp_config
        self.linmot = None
        self.temp_sensor = None

    def __enter__(self):
        # Initialize LinMot controller
        self.linmot = LinMotForceController(**self.linmot_config)
        self.linmot.__enter__()

        # Initialize temperature sensor
        self.temp_sensor = TC08Reader(**self.temp_config)
        self.temp_sensor.__enter__()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.linmot:
            self.linmot.__exit__(exc_type, exc_val, exc_tb)
        if self.temp_sensor:
            self.temp_sensor.__exit__(exc_type, exc_val, exc_tb)

    def record_combined_data(
        self,
        duration_s: int = 20,
        interval_s: float = 0.1,
        csv_path: str = "combined_data.csv",
    ) -> None:
        """Log force, current, position, and temperature data to a single CSV file."""

        # Create header with descriptive temperature channel names
        header = ["system_time", "time_s", "force_raw", "current_raw", "position_raw", "cold_junction_temp"]

        # Add temperature channel headers with descriptive names
        temp_channel_names = {1: "cell_temp", 2: "environment_temp"}
        for ch in self.temp_sensor.channels:
            channel_name = temp_channel_names.get(ch, f"temp_channel_{ch}")
            header.append(channel_name)

        print(f"Starting data recording for {duration_s}s at {interval_s}s intervals...")
        print(f"Recording to: {csv_path}")
        print(f"Header: {header}")

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)

            start = time.time()
            num_samples = int(duration_s // interval_s)

            for i in range(num_samples):
                try:
                    t_sys = time.time()
                    t_elapsed = t_sys - start

                    # Get motor data
                    motor_data = self.linmot.get_motor_data()

                    # Get temperature data
                    temp_data = self.temp_sensor.get_single()

                    # Prepare row data
                    row = [
                        t_sys,
                        t_elapsed,
                        motor_data['force_raw'],
                        motor_data['current_raw'],
                        motor_data['position_raw'],
                        temp_data['cold_junction']
                    ]

                    # Add temperature channel data
                    for ch in self.temp_sensor.channels:
                        row.append(temp_data[f'channel_{ch}'])

                    writer.writerow(row)

                    # Progress indicator with both temperature channels
                    if i % (num_samples // 10) == 0:  # Show progress every 10%
                        progress = (i / num_samples) * 100
                        cell_temp = temp_data.get('channel_1', 'N/A')
                        env_temp = temp_data.get('channel_2', 'N/A')
                        print(f"Progress: {progress:.1f}% - Force: {motor_data['force_raw']:.2f}, "
                              f"Cell: {cell_temp:.2f}°C, Environment: {env_temp:.2f}°C")

                    # Precise timing control
                    elapsed = time.time() - start
                    sleep_time = max(0, interval_s * (i + 1) - elapsed)
                    time.sleep(sleep_time)

                except Exception as e:
                    print(f"Error during data collection at sample {i}: {e}")
                    # Continue collecting data even if one sample fails
                    continue

        print(f"Data recording completed. {num_samples} samples saved to {csv_path}")


def main():
    """Main function to configure and run the combined data logger."""

    # LinMot configuration
    LINMOT_CONFIG = {
        'dll_path': r'C:\Users\Shijie Sun\Desktop\Linear Motor\LinUDP_V2_1_1_0_20210617\LinUDP_V2_DLL\LinUDP.dll',
        'target_ip': "192.109.209.89",
        'host_ip': "192.109.209.100"
    }

    # Temperature sensor configuration
    TEMP_CONFIG = {
        'channels': [1, 2],  # Use channels 1 and 2
        'tc_type': 'K',      # K-type thermocouple
        'mains_hz': 60       # 60Hz mains frequency
    }

    # Data logging parameters
    RECORDING_CONFIG = {
        'duration_s': 1000000000,      # Record for 100 seconds
        'interval_s': 1,     # Sample every 0.25 seconds
        'csv_path': "PID_empty-0.005,0.05,0.01_high force.csv"
    }

    try:
        with CombinedDataLogger(LINMOT_CONFIG, TEMP_CONFIG) as logger:
            print("Connected to both LinMot and TC-08")

            # Prepare LinMot for operation
            logger.linmot.ensure_drive_ready_for_motion()
            print("LinMot drive is ready")
            """
            # Setup force control
            logger.linmot.ensure_force_control_ready(
                position_mm=38,
                velocity=0.1,
                acceleration=0.2,
                force_limit_n=10.0,
                target_force_n=200,
                reset_if_needed=True,
            )
            print("Force control is ready")
            """
            # Start combined data recording
            logger.record_combined_data(**RECORDING_CONFIG)

    except Exception as e:
        print(f"Error during experiment: {e}")
        import traceback
        traceback.print_exc()

    print("System shutdown complete.")


if __name__ == "__main__":
    main()