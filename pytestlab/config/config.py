import re
from typing import Any
from ..errors import InstrumentParameterError, InstrumentConfigurationError

class Config:
    def to_json(self):
        """
        Serialize instance to a JSON-compatible dictionary.

        Returns:
            dict: The serialized representation.
        """
        data = {}
        for attr, value in self.__dict__.items():
            if hasattr(value, 'to_json'):
                # If the attribute has a to_json method, use it to serialize
                data[attr] = value.to_json()
            else:
                # Otherwise, include the attribute as is
                data[attr] = value
        return data

    @staticmethod
    def _validate_parameter(value, expected_type, parameter_name):
        
        if not value or not isinstance(value, expected_type) and isinstance(value, expected_type):
            raise ValueError(f"{parameter_name} must be a {expected_type.__name__}")
        # if list non-empty
        if isinstance(value, list) and len(value) < 0:
            raise ValueError(f"{parameter_name} must be a non-empty list")
            
        return value

class RangeConfig(Config):
    def __init__(self, min_val, max_val):
        self.min_val = float(min_val)
        self.max_val = float(max_val)

    def __repr__(self):
        return f"Range(min_val={self.min_val}, max_val={self.max_val})"
    
    def in_range(self, input_value):
        """
        Validate and return the input value if it is within the range.

        Args:
            input_value (float): The input value to validate.

        Returns:
            float: The validated input value.

        Raises:
            InstrumentParameterError: If the input value is not valid.
        """
        if not isinstance(input_value, (int, float)):
            raise ValueError(f"input_value must be a number. Received: {input_value}")

        if input_value < self.min_val or input_value > self.max_val:
            raise InstrumentParameterError(f"Value out of range: {input_value}. Range: {self.min_val} to {self.max_val}")

        return input_value
    
    def to_json(self):
        """
        Serialize instance to a JSON-compatible dictionary.

        Returns:
            dict: The serialized representation.
        """
        return {
            "min_val": self.min_val,
            "max_val": self.max_val
        }
class SelectionConfig(Config):
    def __init__(self, options):
        self.options = self._validate_parameter(options, list, "options")

    
    def __repr__(self):
        return f"Selection(options={self.options})"
    
    def __getitem__(self, input_command):
        """
        Validate and return the SCPI command if it is valid.

        Args:
        input_command (str): The SCPI command to validate.

        Returns:
        str: The validated SCPI command.

        Raises:
        InstrumentParameterError: If the command is not valid.
        """
        for full_command in self.options:
            if self.is_valid_command(input_command, full_command):
                return full_command
            
        raise InstrumentParameterError(f"Invalid Option: {input_command};\nValid Options: {self.options}")
    
    @staticmethod
    def is_valid_command(input_command, full_command):
        """
        Check if the input SCPI command is either the full command or a valid abbreviation.

        Args:
        input_command (str): The SCPI command to validate.
        full_command (str): The full SCPI command.

        Returns:
        bool: True if valid, False otherwise.
        """
        # Check if the input command is exactly the full command
        if input_command.upper() == full_command.upper():
            return True

        # Check if the input command is a valid abbreviation
        abbreviation = ''.join(word[0] for word in full_command.split()).upper()
        if input_command.upper() == abbreviation:
            return True

        # Check for partial match (e.g., CHANnel matches CHAN)
        partial_match_regex = '^' + ''.join(f'{char}.*' for char in input_command.upper())
        if re.match(partial_match_regex, full_command.upper()):
            return True

        return False
    
    def to_json(self):
        """
        Serialize instance to a JSON-compatible dictionary.

        Returns:
            dict: The serialized representation.
        """
        return self.options
    
    
def ConfigRequires(requirement):
    def decorator(func):
        def wrapped_func(self, *args, **kwargs):
            if self.config.active or not hasattr(self.config, requirement):
                return func(self, *args, **kwargs)
            else:
                raise InstrumentConfigurationError(f"Method '{func.__name__}' requires '{requirement}'. This functionality is not available for this instrument.")
        return wrapped_func
    return decorator