import os
import ctypes
import platform
from ctypes import byref, c_int16, c_int32, c_float, c_char, POINTER


# Direct DLL interface without picosdk wrapper
class DirectTC08:
    def __init__(self, dll_path=r"C:\Program Files (x86)\PicoLog\usbtc08.dll"):
        # Load the DLL directly
        os.add_dll_directory(os.path.dirname(dll_path))
        self.dll = ctypes.WinDLL(dll_path)

        # Define function prototypes based on the programmer's guide
        self._setup_function_prototypes()

        print(f"Using DLL: {dll_path} | Python: {platform.architecture()[0]}")

    def _setup_function_prototypes(self):
        # usb_tc08_open_unit
        self.dll.usb_tc08_open_unit.restype = c_int16
        self.dll.usb_tc08_open_unit.argtypes = []

        # usb_tc08_close_unit
        self.dll.usb_tc08_close_unit.restype = c_int16
        self.dll.usb_tc08_close_unit.argtypes = [c_int16]

        # usb_tc08_set_mains
        self.dll.usb_tc08_set_mains.restype = c_int16
        self.dll.usb_tc08_set_mains.argtypes = [c_int16, c_int16]

        # usb_tc08_set_channel
        self.dll.usb_tc08_set_channel.restype = c_int16
        self.dll.usb_tc08_set_channel.argtypes = [c_int16, c_int16, c_char]

        # usb_tc08_get_single
        self.dll.usb_tc08_get_single.restype = c_int16
        self.dll.usb_tc08_get_single.argtypes = [c_int16, POINTER(c_float), POINTER(c_int16), c_int16]

        # usb_tc08_get_last_error
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

        # Set mains frequency (0 = 50Hz, 1 = 60Hz)
        mains_setting = 1 if self.mains_hz == 60 else 0
        result = self.tc08.dll.usb_tc08_set_mains(self.handle, c_int16(mains_setting))
        if result == 0:
            raise RuntimeError("Failed to set mains frequency")

        # Disable cold junction as measurement channel (still used for compensation)
        self.tc08.dll.usb_tc08_set_channel(self.handle, c_int16(0), c_char(ord(' ')))

        # Configure thermocouple channels
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

        # Create arrays for temperature data (9 channels total: 0-8)
        temps = (c_float * 9)()
        overflow = c_int16(0)

        # Get single conversion
        result = self.tc08.dll.usb_tc08_get_single(
            self.handle,
            temps,  # Pass array directly, not byref(temps)
            byref(overflow),
            c_int16(units)
        )

        if result == 0:
            error_code = self.tc08.dll.usb_tc08_get_last_error(self.handle)
            raise RuntimeError(f"Failed to get readings. Error code: {error_code}")

        # Extract readings for configured channels
        readings = {}
        readings['cold_junction'] = float(temps[0])  # Channel 0 is always cold junction

        for ch in self.channels:
            readings[f'channel_{ch}'] = float(temps[ch])

        # Check for overflows
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


# Example usage
if __name__ == "__main__":
    # Using context manager (recommended)
    try:
        with TC08Reader(channels=[1], tc_type='K', mains_hz=60) as tc:
            print("TC-08 temperature readings:")
            readings = tc.get_single()

            for channel, temp in readings.items():
                print(f"{channel}: {temp:.2f} °C")

    except Exception as e:
        print(f"Error: {e}")

    print("\n" + "=" * 50 + "\n")

    # Manual open/close
    tc = TC08Reader(channels=[1], tc_type='K', mains_hz=60)
    try:
        tc.open()
        readings = tc.get_single()
        print("Manual mode readings:")
        for channel, temp in readings.items():
            print(f"{channel}: {temp:.2f} °C")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        tc.close()