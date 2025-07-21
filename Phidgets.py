import csv
import time
from threading import Lock
from enum import Enum
from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput
from Phidget22.Phidget import *

class PhidgetsForceSensor:
    """
    Thread-safe interface for Phidgets force sensor using VoltageInput.
    """

    def __init__(self, calibration_gain=1.0, calibration_offset=0.0, serial_number=None, channel=0):
        """
        Initialize the Phidgets force sensor.

        Args:
            calibration_gain: Gain value from calibration (N per V/V)
            calibration_offset: Offset from calibration (V/V)
            serial_number: Phidget device serial number (optional)
            channel: Channel number (default 0)
        """
        self.calibration_gain = calibration_gain
        self.calibration_offset = calibration_offset
        self.current_force = 0.0
        self._lock = Lock()
        self.ch = VoltageRatioInput()
        if serial_number is not None:
            self.ch.setDeviceSerialNumber(serial_number)
        self.ch.setChannel(channel)

    def zero(self, samples=100, delay=0.01):
        """
        Automatically calibrate the zero-force voltage ratio offset.

        Args:
            samples: Number of samples to average
            delay: Delay between samples (in seconds)
        """
        print("Zeroing... please make sure no force is applied.")
        total = 0.0
        for _ in range(samples):
            total += self.ch.getVoltageRatio()
            time.sleep(delay)
        self.calibration_offset = total / samples
        print(f"New calibration offset set: {self.calibration_offset:.6e} V/V")

    def on_voltage_ratio_change(self, ch, ratio):
        """
                Callback for phidget sensor. Converts voltage to force.
                Thread-safe update of the current force value.

                Args:
                    ch: Channel object (provided by Phidgets API)
                    voltage: Voltage reading from the sensor
                """
        with self._lock:
            self.current_force = (ratio - self.calibration_offset) * self.calibration_gain

    def on_attach(self, ch):
        """
        Called when the device is attached.

        Args:
            ch: Channel object (provided by Phidgets API)
        """
        print(f"Phidget force sensor attached: {ch.getDeviceSerialNumber()}")
        print(f"Using gain: {self.calibration_gain:.4e} N/(V/V), offset: {self.calibration_offset:.4e} V/V")

    def on_detach(self, ch):
        """
        Called when the device is detached.

        Args:
            ch: Channel object (provided by Phidgets API)
        """
        print(f"Phidget force sensor detached: {ch.getDeviceSerialNumber()}")

    def on_error(self, ch, code, description):
        """
        Called when an error occurs.

        Args:
            ch: Channel object (provided by Phidgets API)
            code: Error code
            description: Error description
        """
        print(f"Phidget error {code}: {description}")

    def open(self):
        """
        Open and prepare the Phidgets device.
        """
        # Set up event handlers
        self.ch.setOnVoltageRatioChangeHandler(self.on_voltage_ratio_change)
        self.ch.setOnAttachHandler(self.on_attach)
        self.ch.setOnDetachHandler(self.on_detach)
        self.ch.setOnErrorHandler(self.on_error)

        # Open the channel and wait for attachment
        self.ch.openWaitForAttachment(5000)

        # Configure the channel
        self.ch.setDataInterval(1000)  # in ms

    def get_force(self):
        """
        Return the last updated force reading in a thread-safe manner.

        Returns:
            Force in newtons
        """
        with self._lock:
            return self.current_force

    def set_data_interval(self, interval_ms):
        """
        Set the data interval for the sensor.

        Args:
            interval_ms: Interval in milliseconds
        """
        self.ch.setDataInterval(interval_ms)

    def set_voltage_change_trigger(self, trigger):
        """
        Set the voltage change trigger.

        Args:
            trigger: Trigger value
        """
        self.ch.setVoltageChangeTrigger(trigger)

    def close(self):
        """
        Close the Phidgets device.
        """
        self.ch.close()
        print("Phidget force sensor closed")

if __name__ == "__main__":
    # Constants from Phidget Control Panel calibration results
    SERIAL_NUMBER = 752561
    CHANNEL = 3
    DURATION_SEC = 10000
    OUTPUT_CSV = "force_data.csv"


    # rated_output = 0.9842e-3  #V/V
    # capacity = 50
    # gain_total = capacity * 9.81 / rated_output
    # print(gain_total)
    # These values are derived from calibration using:
    # Rated Output = 0.9842 mV/V, Capacity = 50 kg
    # Final Gain and Offset from Phidget Control Panel after calibration

    CALIBRATION_GAIN = 498318
    CALIBRATION_OFFSET = -5.875587e-03  # Voltage ratio at zero force

    sensor = PhidgetsForceSensor(
        calibration_gain=CALIBRATION_GAIN,
        calibration_offset=CALIBRATION_OFFSET,
        serial_number=SERIAL_NUMBER,
        channel=CHANNEL
    )

    sensor.open()
    # sensor.zero()
    print("Collecting force data...")

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp (s)", "Force (N)"])
        start = time.time()

        try:
            while time.time() - start < DURATION_SEC:
                timestamp = time.time() - start
                force = sensor.get_force()
                print(f"{timestamp:.2f}s: {force:.3f} N")
                writer.writerow([timestamp, force])
                time.sleep(1)
        except KeyboardInterrupt:
            print("Logging stopped manually.")
        finally:
            sensor.close()

    print(f"Data collection complete. Saved to {OUTPUT_CSV}.")