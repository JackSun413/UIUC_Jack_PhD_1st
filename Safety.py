import numpy as np
from collections import deque


def check_safety(voltage, force, max_voltage=5.0, max_force=100.0):
    """
    Return True if everything is safe; False if we exceed thresholds.

    Args:
        voltage: Current voltage
        force: Current force
        max_voltage: Maximum allowed voltage
        max_force: Maximum allowed force

    Returns:
        True if safe, False otherwise
    """
    if abs(voltage) > max_voltage:
        print(f"Voltage {voltage:.2f} exceeds limit {max_voltage:.2f}")
        return False
    if abs(force) > max_force:
        print(f"Force {force:.2f} exceeds limit {max_force:.2f}")
        return False
    return True


def dynamic_safety_check(voltage, force, history, max_voltage=4.3, max_force=100.0,
                         max_voltage_rate=0.2, max_force_rate=10.0, window_size=5):
    """
    Enhanced safety check that monitors both absolute values and rates of change.

    Args:
        voltage: Current voltage
        force: Current force
        history: List of past (voltage, force, timestamp) tuples
        max_voltage: Maximum allowed voltage
        max_force: Maximum allowed force
        max_voltage_rate: Maximum allowed voltage change rate (V/s)
        max_force_rate: Maximum allowed force change rate (N/s)
        window_size: Number of samples to use for rate calculation

    Returns:
        True if safe, False otherwise
    """
    # Check absolute thresholds first
    if not check_safety(voltage, force, max_voltage, max_force):
        return False

    # Need enough history to check rates
    if len(history) > window_size:
        # Calculate time differences
        time_now = history[-1][2]
        time_past = history[-window_size][2]
        dt = time_now - time_past

        if dt > 0:  # Avoid division by zero
            # Calculate voltage rate of change
            voltage_past = history[-window_size][0]
            voltage_rate = abs(voltage - voltage_past) / dt

            # Calculate force rate of change
            force_past = history[-window_size][1]
            force_rate = abs(force - force_past) / dt

            # Check rate limits
            if voltage_rate > max_voltage_rate:
                print(f"Voltage rate {voltage_rate:.2f} V/s exceeds limit {max_voltage_rate:.2f} V/s")
                return False

            if force_rate > max_force_rate:
                print(f"Force rate {force_rate:.2f} N/s exceeds limit {max_force_rate:.2f} N/s")
                return False

    return True


class SafetyMonitor:
    """
    Comprehensive safety monitoring system with history tracking and various safety checks.
    """

    def __init__(self, max_voltage=5.0, max_force=100.0,
                 max_voltage_rate=0.5, max_force_rate=10.0,
                 history_length=100):
        """
        Initialize the safety monitor.

        Args:
            max_voltage: Maximum allowed voltage
            max_force: Maximum allowed force
            max_voltage_rate: Maximum allowed voltage change rate (V/s)
            max_force_rate: Maximum allowed force change rate (N/s)
            history_length: Number of samples to keep in history
        """
        self.max_voltage = max_voltage
        self.max_force = max_force
        self.max_voltage_rate = max_voltage_rate
        self.max_force_rate = max_force_rate

        # Use deque for efficient history management
        self.history = deque(maxlen=history_length)

        # Track consecutive warnings
        self.consecutive_warnings = 0
        self.max_consecutive_warnings = 3

        # Flag for system state
        self.is_safe = True

    def add_sample(self, voltage, force, timestamp):
        """
        Add a new sample to the history.

        Args:
            voltage: Current voltage
            force: Current force
            timestamp: Current timestamp
        """
        self.history.append((voltage, force, timestamp))

    def check(self, voltage, force, timestamp):
        """
        Perform comprehensive safety check.

        Args:
            voltage: Current voltage
            force: Current force
            timestamp: Current timestamp

        Returns:
            True if safe, False otherwise
        """
        # Add current sample to history
        self.add_sample(voltage, force, timestamp)

        # Perform basic safety check
        basic_safe = check_safety(voltage, force, self.max_voltage, self.max_force)

        if not basic_safe:
            self.is_safe = False
            return self.is_safe

        # Perform dynamic safety check if we have enough history
        if len(self.history) > 5:
            dynamic_safe = dynamic_safety_check(
                voltage, force, list(self.history),
                self.max_voltage, self.max_force,
                self.max_voltage_rate, self.max_force_rate
            )
        else:
            dynamic_safe = True

        # Update consecutive warnings counter
        if not dynamic_safe:
            self.consecutive_warnings += 1
        else:
            self.consecutive_warnings = 0


        # System is unsafe if too many consecutive warnings
        if self.consecutive_warnings >= self.max_consecutive_warnings:
            self.is_safe = False
            print(f"SAFETY CRITICAL: {self.consecutive_warnings} consecutive warnings")

        return self.is_safe