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

    def _get_state(self):
        return self.ACI.getStateMachineState(self.target_ip)

    def _pretty_state(self, st=None):
        st = st if st is not None else self._get_state()
        try:
            return f"{st} ({int(st)})"
        except Exception:
            return str(st)

    def ensure_drive_ready_for_motion(self, timeout=30):
        """
        Simple, reliable bring-up: ack errors, call SwitchOn(), wait for OperationEnabled.
        """
        import time

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
    """
            # Wait for isHomed to become True
            while not self.ACI.isHomed(self.target_ip):
                if self.ACI.isError(self.target_ip):
                    errmsg = self.ACI.getDLLError()
                    raise RuntimeError(f"Error during homing: {errmsg}")
                if time.time() - t0 > timeout:
                    raise TimeoutError("Timed out waiting for homing.")
                time.sleep(0.5)

            print("Homing complete.")

        print("Drive is Operation Enabled.")
    """
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
        print("changing force now...")
        return self.ACI.LMfc_IncrementActPosWithHigherForceCtrlLimitAndTargetForce(
            self.target_ip,
            float(position_mm),
            float(max_velocity),
            float(acceleration),
            float(force_limit_n),
            float(target_force_n),
        )

    def ensure_force_control_ready(
            self,
            position_mm: float,
            velocity: float = 0.1,
            acceleration: float = 0.2,
            force_limit_n: float = 20.0,
            target_force_n: float = 200.0,
            reset_if_needed: bool = True
    ) -> bool:
        """
        Ensure the drive is in a valid state for force control.
        If already in force mode, it updates the target force.
        If not, it sends a force-control motion command.

        Args:
            position_mm: Position increment to apply if force control is re-triggered.
            velocity: Velocity for the force control move.
            acceleration: Acceleration for the force control move.
            force_limit_n: Threshold force to switch from position to force control.
            target_force_n: Desired target force.
            reset_if_needed: If True, will reset into force control mode if not active.
        Returns:
            True if ready or successfully entered force control mode, False otherwise.
        """
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
        # Optionally reset force control mode safely
        self.ACI.LMfc_GoToPosRstForceCtrlSetI(
            self.target_ip,
            float(position_mm - 1),
            float(velocity),
            float(acceleration),
            float(acceleration),
        )
        time.sleep(0.2)

        # Then re-engage force control mode with target force
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

    def record_force_current_position(
            self,
            duration_s: int = 20,
            interval_s: float = 0.1,
            csv_path: str = "linmot_data.csv",
    ) -> None:
        """Log force, current and position data to `csv_path`."""
        import csv

        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["system_time","time_s", "force_raw", "current_raw", "position_raw"]
            )
            start = time.time()
            for i in range(int(duration_s // interval_s)):
                t_sys = time.time()
                t_elapsed = float(t_sys) - float(start)
                # If functions with timestamp are used, monitoring channel 1 on all drives must be configured to UPID 82h (Operating Sub Hours) !
                force = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 2)
                current = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 3)
                position = self.ACI.getMonitoringChannelWithTimestamp(self.target_ip, 4)

                writer.writerow(
                    [t_sys, t_elapsed, position.value, force.value, current.value]
                )
                elapsed = time.time() - start
                time.sleep(max(0, interval_s * (i + 1) - elapsed))

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


if __name__ == "__main__":
    LINMOT_DLL_PATH = r'C:\Users\Shijie Sun\Desktop\Linear Motor\LinUDP_V2_1_1_0_20210617\LinUDP_V2_DLL\LinUDP.dll'
    LINMOT_TARGET_IP = "192.109.209.89"
    LINMOT_HOST_IP = "192.109.209.100"

    try:
        with LinMotForceController(
                dll_path=LINMOT_DLL_PATH,
                target_ip=LINMOT_TARGET_IP,
                host_ip=LINMOT_HOST_IP,
        ) as linmot:
            print("Connected to LinMot")
            linmot.ensure_drive_ready_for_motion()
            print("Drive is ready")
            # linmot.move_abs(10,0.005,1,1)

            linmot.ensure_force_control_ready(
                position_mm=37,
                velocity=0.1,
                acceleration=0.2,
                force_limit_n=10.0,
                target_force_n=200.0,
                reset_if_needed=True,
            )
            

            print("Recording force/current/position for 100 days...")
            linmot.record_force_current_position(
                duration_s=10000000,
                interval_s=0.25,
                csv_path="linmot_data_Test 6.csv",
            )
    except Exception as e:
        print(f"Error during experiment: {e}")

    print("System off.")
