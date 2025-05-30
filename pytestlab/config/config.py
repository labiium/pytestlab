from __future__ import annotations
import re
from typing import Any, List
from pydantic import BaseModel, validator

from ..errors import InstrumentParameterError, InstrumentConfigurationError
from .base import Range as NewRangeModel # Import the Pydantic Range model

# Alias for backward compatibility
RangeConfig = NewRangeModel

class Selection(BaseModel):
    options: List[str]

    @validator('options')
    def check_options_not_empty(cls, v):
        if not v:
            raise ValueError("Selection options list cannot be empty")
        return v

    def get_matching_option(self, input_command: str) -> str:
        """
        Validate and return the command if it is valid.
        Tries to match full command, abbreviation, or partial match.
        """
        input_cmd_upper = str(input_command).upper()
        for option in self.options:
            option_upper = str(option).upper()
            if input_cmd_upper == option_upper:
                return option

            # Check for abbreviation (e.g., "CHAN" for "CHANNEL")
            # This simple abbreviation check might need refinement for more complex SCPI
            # For now, let's assume abbreviations are explicitly listed or handled by direct match.
            # A more robust SCPI parser would be needed for general abbreviation handling.

            # Check for partial match (e.g., input "CHAN" matches "CHANNEL1")
            # This logic is tricky and can lead to ambiguity.
            # The original `is_valid_command` had a specific regex for this.
            # For Pydantic, direct validation against `options` is cleaner.
            # If advanced matching is needed, it should be outside the Pydantic model,
            # or the `options` should contain all valid forms (full, common abbreviations).

            # Simplified check: if input is a prefix of an option
            if option_upper.startswith(input_cmd_upper): # Basic prefix match
                 # This could be ambiguous if "CH" could match "CHANNEL" and "CHOICE"
                 # For now, let's assume this is desired or options are distinct enough.
                 # A more robust solution might involve a priority or exact match first.
                 # The original code had more complex matching logic.
                 # Replicating it perfectly here might be overly complex for a Pydantic model.
                 # The user might need to adjust this matching logic based on requirements.
                pass # Placeholder for more advanced matching if needed.

        # Fallback to the original regex-based partial match if no direct/prefix match found
        # This is to maintain closer behavior to the original `is_valid_command`
        for option in self.options:
            option_upper = str(option).upper()
            # Check for partial match (e.g., CHANnel matches CHAN)
            # This regex tries to match if input_command is an initial substring of full_command,
            # allowing for characters in between (e.g. CHAN for CHANNEL)
            # Example: input_command = "CHAN", full_command = "CHANNEL"
            # regex = '^C.*H.*A.*N.*' (if we build it char by char)
            # A simpler startswith is often sufficient if abbreviations are not complex.
            # The original regex was: partial_match_regex = '^' + ''.join(f'{char}.*' for char in input_command.upper())
            # if re.match(partial_match_regex, option_upper):
            #     return option
            # The above regex is quite permissive. A direct startswith is usually safer.
            if option_upper.startswith(input_cmd_upper): # Re-evaluating, simpler is better for Pydantic
                return option


        raise InstrumentParameterError(f"Invalid Option: '{input_command}'. Valid Options: {self.options}")

    class Config:
        validate_assignment = True

# Alias for backward compatibility
SelectionConfig = Selection

# The old Config class and ChannelsConfig are removed as Pydantic handles this.
# Individual instrument configs will use List[SpecificChannelModel]

def ConfigRequires(requirement):
    def decorator(func):
        def wrapped_func(self, *args, **kwargs):
            # This decorator might need adjustment if `self.config` changes structure
            # due to Pydantic. Assuming it's used with classes that will still have
            # a `config` attribute that is a Pydantic model.
            config_obj = getattr(self, "config", None)
            if config_obj and hasattr(config_obj, requirement):
                return func(self, *args, **kwargs)
            else:
                # Check if the requirement is a field in the Pydantic model
                if config_obj and isinstance(config_obj, BaseModel) and requirement in config_obj.__fields__:
                     if getattr(config_obj, requirement) is not None: # Check if field is set
                        return func(self, *args, **kwargs)

                raise InstrumentConfigurationError(
                    f"Method '{func.__name__}' requires '{requirement}'. "
                    f"This functionality is not available or not configured for this instrument."
                )
        return wrapped_func
    return decorator