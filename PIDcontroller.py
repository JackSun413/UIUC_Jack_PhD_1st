class PIDController:
    def __init__(self, kp=1.0, ki=0.1, kd=0.01, setpoint=0.0, dt=0.1, output_limits=None):
        """
        Enhanced PID controller with anti-windup protection.

        Args:
            kp: Proportional gain
            ki: Integral gain
            kd: Derivative gain
            setpoint: Target value
            dt: Time step (seconds)
            output_limits: Tuple of (min, max) output values or None for no limits
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.dt = dt

        # Output limits
        self.output_limits = output_limits

        # PID state
        self.integral = 0.0
        self.prev_error = 0.0
        self.last_output = 0.0

        # Initialize history for monitoring
        self.error_history = []
        self.output_history = []
        self.max_history = 100

    def update(self, measured_value):
        """
        Compute PID output given a measured value.
        Uses anti-windup protection to prevent integral term from growing too large.

        Args:
            measured_value: Current process variable

        Returns:
            Control output
        """
        # Calculate error
        error = self.setpoint - measured_value

        # Store error history
        self.error_history.append(error)
        if len(self.error_history) > self.max_history:
            self.error_history.pop(0)

        # Calculate PID terms
        p_term = self.kp * error

        # Update integral with anti-windup
        self.integral += error * self.dt
        i_term = self.ki * self.integral

        # Calculate derivative term (on error)
        d_term = self.kd * (error - self.prev_error) / self.dt

        # Calculate total output
        output = p_term + i_term + d_term

        # Apply output limits if specified
        if self.output_limits is not None:
            output_limited = max(self.output_limits[0], min(output, self.output_limits[1]))

            # Anti-windup: adjust integral term if output is saturated
            if output != output_limited:
                # Adjust integral to prevent it from growing further in the wrong direction
                self.integral -= (output - output_limited) * self.dt / self.ki if self.ki != 0 else 0

            output = output_limited

        # Store state for next iteration
        self.prev_error = error
        self.last_output = output

        # Store output history
        self.output_history.append(output)
        if len(self.output_history) > self.max_history:
            self.output_history.pop(0)

        return output

    def reset(self):
        """
        Reset the PID controller state.
        """
        self.integral = 0.0
        self.prev_error = 0.0
        self.error_history = []
        self.output_history = []

    def set_tunings(self, kp=None, ki=None, kd=None):
        """
        Update the PID controller tuning parameters.

        Args:
            kp: New proportional gain or None to keep current value
            ki: New integral gain or None to keep current value
            kd: New derivative gain or None to keep current value
        """
        if kp is not None:
            self.kp = kp
        if ki is not None:
            self.ki = ki
        if kd is not None:
            self.kd = kd

    def set_setpoint(self, setpoint):
        """
        Update the controller setpoint.

        Args:
            setpoint: New target value
        """
        self.setpoint = setpoint