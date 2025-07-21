"""Minimal wrapper around the LinUDP .NET API used to control a LinMot motor."""

from __future__ import annotations

import clr
import time
from contextlib import AbstractContextManager
from typing import Optional

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

    def homing_and_enable(self, timeout=60):
        if not self.ACI.isSwitchOnActive(self.target_ip):
            print("Switching on drive...")
            self.ACI.SwitchOn(self.target_ip)
        if not self.ACI.isHomed(self.target_ip):
            print("Starting homing procedure...")
            homing_started = self.ACI.Homing(self.target_ip)
            print(f"Homing started? {homing_started}")
            t0 = time.time()
            while not self.ACI.isHomed(self.target_ip):
                if self.ACI.isError(self.target_ip):
                    print("Drive reported an error during homing.")
                    print("Error text:", self.ACI.LMcf_GetErrorTxt(self.target_ip))
                    raise RuntimeError("Homing failed with error!")
                if time.time() - t0 > timeout:
                    raise TimeoutError("Homing timed out after {} seconds.".format(timeout))
                time.sleep(0.5)
        print("Drive homed!")
        return True

    def set_force(self, force_n):
        return self.ACI.LMfc_ChangeTargetForce(self.target_ip, float(force_n))

    def stop_force(self):
        return self.set_force(0.0)

    def disconnect(self):
        self.ACI.CloseConnection()
        self.connected = False

    def move_with_force_limit_and_target(
        self,
        position_mm: float,
        max_velocity: float,
        acceleration: float,
        force_limit_n: float,
        target_force_n: float,
    ) -> bool:
        """Move to a position while controlling force."""
        return self.ACI.LMfc_GoToPosForceCtrlHighLim(
            self.target_ip,
            float(position_mm),
            float(max_velocity),
            float(acceleration),
            float(force_limit_n),
            float(target_force_n),
        )

    def record_force_current_position(
        self,
        duration_s: int = 1800,
        interval_s: float = 1.0,
        csv_path: str = "linmot_data.csv",
    ) -> None:
        """Log force, current and position data to ``csv_path``."""
        import csv

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["drive_timestamp_ms", "system_time_s", "force_raw", "position_raw", "current_raw"]
            )
            start = time.time()
            for i in range(int(duration_s // interval_s)):
                t_sys = time.time()
                force = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 1)
                position = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 2)
                current = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 3)
                writer.writerow(
                    [force.Timestamp, t_sys, force.value, position.value, current.value]
                )
                elapsed = time.time() - start
                time.sleep(max(0, interval_s * (i + 1) - elapsed))


if __name__ == "__main__":
    LINMOT_DLL_PATH = r'C:\Users\12500\Downloads\LinUDP_V2_1_1_0_20210617\LinUDP\LinUDP.dll'
    LINMOT_TARGET_IP = "192.109.209.89"
    LINMOT_HOST_IP = "192.109.209.100"

    try:
        with LinMotForceController(
                dll_path=LINMOT_DLL_PATH,
                target_ip=LINMOT_TARGET_IP,
                host_ip=LINMOT_HOST_IP,
        ) as linmot:
            print("Connected to LinMot")
            linmot.homing_and_enable()
            print("Drive homed")

            linmot.move_with_force_limit_and_target(
                position_mm=79.0,
                max_velocity=0.005,
                acceleration=1,
                force_limit_n=50.0,
                target_force_n=100.0,
            )

            print("Recording force/current/position for 30 minutes...")
            linmot.record_force_current_position(
                duration_s=20,
                interval_s=1,
                csv_path="linmot_data.csv",
            )
    except Exception as e:
        print(f"Error during experiment: {e}")

    print("System off.")
