import os
import time
import sys
from contextlib import AbstractContextManager
from threading import Lock
from enum import Enum

# Import the kbio libraries
from kbio.kbio_api import KBIO_api
from kbio.kbio_types import BOARD_TYPE, ERROR
from kbio.kbio_types import I_RANGE, PROG_STATE
from kbio.utils import exception_brief, warn_diff
from kbio.c_utils import c_is_64b
from kbio.kbio_tech import ECC_parm, make_ecc_parm, make_ecc_parms, get_experiment_data, get_info_data


class ChargeState(Enum):
    """Enum to track battery charging state based on current direction."""
    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2


class BioLogicInterface(AbstractContextManager):
    """
    Interface for BioLogic potentiostats/galvanostats using EC-Lab Development Package.
    Provides a higher-level interface for connecting, reading values, and controlling channels.
    """

    # CP technique parameter definitions
    CP_PARAMS = {
        "current": ECC_parm("I", float),
        "duration": ECC_parm("Duration", float),
        "record_interval": ECC_parm("Record_every_dE", float),
        "voltage_limit": ECC_parm("Ew_limit", float),
        "timebase": ECC_parm("tb", int),
    }

    def __init__(self, eclib_dll_path, blfind_dll_path=None):
        """
        Initialize the BioLogic interface.

        Args:
            eclib_dll_path: Path to EClib.dll or EClib64.dll
            blfind_dll_path: Path to blfind.dll (optional)
        """
        self.api = KBIO_api(eclib_file=eclib_dll_path, blfind_file=blfind_dll_path)
        self.connection_id = None
        self.connected = False
        self._lock = Lock()  # For thread safety
        self.device_info = None

    def __enter__(self) -> "BioLogicInterface":  # type: ignore[override]
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.shutdown()

    def connect(self, address, timeout_s=5):
        """
        Connect to a BioLogic instrument.

        Args:
            address: Instrument address (e.g., "USB0" or IP address)
            timeout_s: Connection timeout in seconds

        Returns:
            True if connection successful, False otherwise
        """
        try:
            print(f"Connecting to {address} ...")
            self.connection_id, self.device_info = self.api.Connect(address, timeout_s)
            self.connected = True
            print("Connected successfully to BioLogic device.")
            return True
        except Exception as e:
            print("Connection error:", exception_brief(e, extended=True))
            return False

    def get_board_type(self, channel):
        """
        Get the board type for a specific channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            Board type code
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        # Note: The API expects 0-based channel index
        return self.api.GetChannelBoardType(self.connection_id, channel - 1)

    def load_firmware(self, channel, firmware_path, fpga_path=None, force=False):
        """
        Load firmware for a channel.

        Args:
            channel: Channel number (1-based)
            firmware_path: Path to firmware file
            fpga_path: Path to FPGA file (optional)
            force: Force reload if already loaded

        Returns:
            True if successful, False otherwise
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        try:
            ch_map = self.api.channel_map({channel})
            self.api.LoadFirmware(self.connection_id, ch_map,
                                  firmware=firmware_path,
                                  fpga=fpga_path,
                                  force=force)
            return True
        except ERROR as e:
            # Handle specific firmware errors as suggested by colleague
            if e == ERROR.FIRM_FIRMWARENOTLOADED:
                print("Firmware not loaded, forcing reload...")
                try:
                    self.api.LoadFirmware(self.connection_id, ch_map,
                                          firmware=firmware_path,
                                          fpga=fpga_path,
                                          force=True)
                    return True
                except Exception as e2:
                    print("Forced firmware load error:", exception_brief(e2, extended=True))
                    return False
            else:
                print("Firmware load error:", exception_brief(e, extended=True))
                return False
        except Exception as e:
            print("Firmware load error:", exception_brief(e, extended=True))
            return False

    def get_channel_info(self, channel):
        """
        Get information about a specific channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            Channel information
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        return self.api.GetChannelInfo(self.connection_id, channel)

    def is_channel_running(self, channel):
        """Return True if the specified channel is currently running."""
        info = self.get_channel_info(channel)
        return PROG_STATE(info.State) == PROG_STATE.RUN

    def is_step_finished(self, channel):
        """Compatibility helper used by Main.py."""
        return not self.is_channel_running(channel)

    def get_plugged_channels(self):
        """
        Get a list of available channels.

        Returns:
            List of available channel numbers (1-based)
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        channels = []
        for i in range(1, 17):  # Trying channels 1-16
            try:
                info = self.get_channel_info(i)
                # Instead of relying on IsConnected, check if info itself is valid
                channels.append(i)  # Assume channel is usable if no exception
            except Exception as e:
                # If cannot read info, skip
                continue
        return channels

    def start_channel(self, channel):
        """
        Start a channel.

        Args:
            channel: Channel number (1-based)
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        self.api.StartChannel(self.connection_id, channel)
        print(f"Channel {channel} started")

    def stop_channel(self, channel):
        """
        Stop a channel.

        Args:
            channel: Channel number (1-based)
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        self.api.StopChannel(self.connection_id, channel)
        print(f"Channel {channel} stopped")

    def read_values(self, channel):
        """
        Read current values from a channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            CurrentValues object with Ewe, I, etc.
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        with self._lock:
            return self.api.GetCurrentValues(self.connection_id, channel)

    def read_voltage(self, channel):
        """
        Read voltage (Ewe) from a channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            Voltage in volts
        """
        values = self.read_values(channel)
        return values.Ewe

    def read_current(self, channel):
        """
        Read current (I) from a channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            Current in amps
        """
        values = self.read_values(channel)
        return values.I

    def create_cp_parameters(self, current, duration, record_interval, voltage_limit, timebase=1):
        """
        Create parameters for Chronopotentiometry (CP) technique.

        Args:
            current: Applied current in amps (positive for charge, negative for discharge)
            duration: Duration in seconds
            record_interval: Data recording interval in seconds
            voltage_limit: Cutoff voltage in volts
            timebase: Time base for the technique (default=1)

        Returns:
            ECC parameters object for CP technique
        """
        params = [
            make_ecc_parm(self.api, self.CP_PARAMS["current"], current),
            make_ecc_parm(self.api, self.CP_PARAMS["duration"], duration),
            make_ecc_parm(self.api, self.CP_PARAMS["record_interval"], record_interval),
            make_ecc_parm(self.api, self.CP_PARAMS["voltage_limit"], voltage_limit)
        ]

        if timebase != 1:
            params.append(make_ecc_parm(self.api, self.CP_PARAMS["timebase"], timebase))

        return make_ecc_parms(self.api, *params)

    def load_cp_technique(self, channel, current, duration, record_interval, voltage_limit):
        """
        Load Chronopotentiometry (CP) technique onto a channel.

        Args:
            channel: Channel number (1-based)
            current: Applied current in amps (positive for charge, negative for discharge)
            duration: Duration in seconds
            record_interval: Data recording interval in seconds
            voltage_limit: Cutoff voltage in volts

        Returns:
            True if technique loaded successfully, False otherwise
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        try:
            params = self.create_cp_parameters(current, duration, record_interval, voltage_limit)
            self.api.LoadTechnique(self.connection_id, channel, "cp.ecc", params)
            return True
        except Exception as e:
            print("Error loading CP technique:", exception_brief(e, extended=True))
            return False

    def determine_charge_state(self, current):
        """
        Determine battery charge state based on current direction.

        Args:
            current: Current in amps

        Returns:
            ChargeState enum value
        """
        if current > 0.01:  # Small positive threshold (charging)
            return ChargeState.CHARGING
        elif current < -0.01:  # Small negative threshold (discharging)
            return ChargeState.DISCHARGING
        return ChargeState.IDLE

    def get_data(self, channel):
        """
        Get raw data from the channel.

        Args:
            channel: Channel number (1-based)

        Returns:
            Raw data object from the API
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        return self.api.GetData(self.connection_id, channel)

    def get_experiment_data(self, channel, data=None):
        """
        Get experiment data in a more accessible format.

        Args:
            channel: Channel number (1-based)
            data: Raw data from get_data() (optional, will be fetched if not provided)

        Returns:
            Tuple of (status, technique_name, data_points)
            where data_points is a list of dictionaries with experiment values
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        if data is None:
            data = self.get_data(channel)

        board_type = self.get_board_type(channel)
        status, tech_name = get_info_data(self.api, data)
        data_points = list(get_experiment_data(self.api, data, tech_name, board_type))

        return status, tech_name, data_points

    def run_cp_cycle(self, channel, charge_current, discharge_current,
                     cutoff_voltage, duration, record_interval,
                     output_file=None, cycles=1):
        """
        Run a complete charge-discharge cycle using CP technique.

        Args:
            channel: Channel number (1-based)
            charge_current: Charge current in amps (positive value)
            discharge_current: Discharge current in amps (negative value)
            cutoff_voltage: Cutoff voltage in volts
            duration: Maximum duration per phase in seconds
            record_interval: Data recording interval in seconds
            output_file: Path to output CSV file (optional)
            cycles: Number of cycles to run

        Returns:
            A list of collected data points
        """
        if not self.connected:
            raise RuntimeError("Not connected to instrument")

        # Ensure currents have the correct sign
        charge_current = abs(charge_current)
        discharge_current = -abs(discharge_current)

        all_data = []
        file_obj = None

        if output_file:
            file_obj = open(output_file, "w")
            file_obj.write("Cycle,Phase,Time(s),Voltage(V),Current(A),State\n")

        try:
            for cycle in range(1, cycles + 1):
                print(f"\nStarting cycle {cycle} of {cycles}")

                # Charge phase
                print("Starting charge phase...")
                self.load_cp_technique(channel, charge_current, duration, record_interval, cutoff_voltage)
                self.start_channel(channel)

                charge_data = self._process_phase(channel, "Charge", cutoff_voltage, file_obj, cycle)
                all_data.extend(charge_data)

                # Discharge phase
                print("Starting discharge phase...")
                lower_cutoff = cutoff_voltage - 1.0  # Default lower cutoff voltage
                self.load_cp_technique(channel, discharge_current, duration, record_interval, lower_cutoff)
                self.start_channel(channel)

                discharge_data = self._process_phase(channel, "Discharge", lower_cutoff, file_obj, cycle)
                all_data.extend(discharge_data)

            return all_data

        except KeyboardInterrupt:
            print("User interrupted operation")
            return all_data
        except Exception as e:
            print("Error during CP cycle:", exception_brief(e, extended=True))
            return all_data
        finally:
            if file_obj:
                file_obj.close()

    def _process_phase(self, channel, phase_name, cutoff_voltage, file_obj=None, cycle=1):
        """
        Process a single charge or discharge phase.

        Args:
            channel: Channel number (1-based)
            phase_name: Name of the phase ("Charge" or "Discharge")
            cutoff_voltage: Cutoff voltage value
            file_obj: File object for data logging (optional)
            cycle: Current cycle number

        Returns:
            List of data points collected during this phase
        """
        data_points = []
        check_interval = 0.5  # Polling interval in seconds

        while True:
            try:
                status, tech_name, samples = self.get_experiment_data(channel)

                for sample in samples:
                    # Extract key data
                    timestamp = sample.get('t', 0)
                    voltage = sample.get('Ewe', 0)
                    current = sample.get('I', 0) if 'I' in sample else sample.get('Iwe', 0)
                    state = self.determine_charge_state(current)

                    # Store data point
                    data_point = {
                        'cycle': cycle,
                        'phase': phase_name,
                        'time': timestamp,
                        'voltage': voltage,
                        'current': current,
                        'state': state.name
                    }
                    data_points.append(data_point)

                    # Log to file if provided
                    if file_obj:
                        record = f"{cycle},{phase_name},{timestamp},{voltage},{current},{state.name}\n"
                        file_obj.write(record)
                        file_obj.flush()

                    # Check for voltage limit based on phase
                    if phase_name == "Charge" and voltage >= cutoff_voltage:
                        print(f"Charge complete: reached cutoff voltage {cutoff_voltage}V")
                        self.stop_channel(channel)
                        return data_points
                    elif phase_name == "Discharge" and voltage <= cutoff_voltage:
                        print(f"Discharge complete: reached cutoff voltage {cutoff_voltage}V")
                        self.stop_channel(channel)
                        return data_points

                # Check if the channel has stopped
                if status == "STOP":
                    print(f"{phase_name} complete: technique finished")
                    return data_points

                time.sleep(check_interval)

            except Exception as e:
                print(f"Error during {phase_name}: {exception_brief(e)}")
                self.stop_channel(channel)
                return data_points

    def disconnect(self):
        """
        Disconnect from the instrument.
        """
        if self.connected:
            self.api.Disconnect(self.connection_id)
            self.connected = False
            self.connection_id = None
            print("Disconnected from instrument")

    def shutdown(self):
        """
        Emergency shutdown - stop all channels and disconnect.
        """
        if self.connected:
            try:
                # Try to stop all possible channels
                for channel in range(1, 17):
                    try:
                        self.stop_channel(channel)
                    except:
                        pass
                self.disconnect()
            except:
                pass  # Ensure we don't propagate exceptions during emergency shutdown


if __name__ == "__main__":
    ECLIB_PATH = "D:/EC-Lab Development Package/lib/EClib64.dll"
    BLFIND_PATH = "D:/EC-Lab Development Package/lib/blfind64.dll"

    DEVICE_ADDRESS = "192.109.209.128"
    OUTPUT_FILE = "cp_test_data.csv"

    firmware_path = "D:/EC-Lab Development Package/lib/kernel4.bin"
    fpga_path = "D:/EC-Lab Development Package/lib/Vmp_iv_0395_aa.xlx"

    with BioLogicInterface(ECLIB_PATH, BLFIND_PATH) as bio:
        try:
            if not bio.connect(DEVICE_ADDRESS):
                print("Failed to connect to the real device")
                sys.exit(1)

            channels = bio.get_plugged_channels()
            if not channels:
                print("No connected channels found")
                sys.exit(1)

            test_channel = channels[0]
            bio.load_firmware(test_channel, firmware_path, fpga_path, force=True)

            bio.run_cp_cycle(
                channel=test_channel,
                charge_current=0.005,
                discharge_current=-0.005,
                cutoff_voltage=4.3,
                duration=60,
                record_interval=10.0,
                output_file=OUTPUT_FILE,
                cycles=1,
            )
            print(f"Data saved to {OUTPUT_FILE}")
        except Exception as e:
            print(f"Test failed: {e}")
    time.sleep(1)