import logging
import threading
import os
from colorama import init, Fore, Style

init(autoreset=True)

CONSOLE_LOG_LEVEL = logging.INFO
FILE_LOG_LEVEL = logging.DEBUG

CONSOLE_FORMATTING = '-- %(asctime)s -- %(message)s --'
CONSOLE_DATE_FORMAT = '%H:%M:%S'

DEBUG_FORMATTER = logging.Formatter('%(levelname)s - %(name)s - %(asctime)s - %(filename)s -  %(funcName)s - %(lineno)d - %(message)s')

EXTERNAL_LOGGER_NAMES = ['httpcore', 'openai._base_client']

class ColoredConsoleFormatter(logging.Formatter):
    """Custom formatter to add colors to console output for different log levels."""
    COLOR_MAP = {
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def __init__(self, fmt=CONSOLE_FORMATTING, datefmt=CONSOLE_DATE_FORMAT, style='%'):
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)


    def format(self, record):
        color = self.COLOR_MAP.get(record.levelno)
        message = super().format(record)
        if color:
            message = color + message
        return message

#A Thread-safe singleton of our logging class
class SetupLogging:
    """
    This is the global logging class. It has two loggers. Debug logger and Console logger. Debug logger logs at debug level to a file and console logger
    logs to the console for the customer. This is a singleton. We are also taking care of external library loggers and directing them to our debug file. 
    Refer the EXTERNAL_LOGGER_NAMES list.
    """
    # A class variable that will hold a lock for thread-safe initialisation
    _instance_lock = threading.Lock()
    _initialized = False  # Class-level flag to prevent multiple initialisations

    # Overridding the __new__ method to implement Singleton behavior
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, '_instance'):  # Checking if an instance doesn't already exist
            with cls._instance_lock:  # Ensuring thread-safe initialization
                if not hasattr(cls, '_instance'):  # Double checking to avoid race condition
                    cls._instance = super(SetupLogging, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self.__class__._initialized :  # Prevent reinitialization of instance
            self._console_logger=None
            self._debug_logger=None
            self.initialize_loggers()
            self.__class__._initialized = True

    def create_logger(self, name, logging_level):
        # Creating or retrieving a logger with the given name
        new_logger = logging.getLogger(name)
        new_logger.setLevel(logging_level)
        new_logger.propagate = False # Preventing the logger from propagating messages to the root logger
        return new_logger
    
    def add_handler(self, input_logger, formatter, handler, logging_level):
        if not any(isinstance(h, type(handler)) for h in input_logger.handlers):
            # Initializing and setting handler if not already set
            new_handler = handler
            new_handler.setLevel(logging_level)
            new_handler.setFormatter(formatter)
            input_logger.addHandler(new_handler)
    
    def add_handlers_to_loggers(self, directory):
        self.add_handler(self._debug_logger, DEBUG_FORMATTER, logging.FileHandler(directory), FILE_LOG_LEVEL)
        
        colored_console_formatter = ColoredConsoleFormatter()
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(colored_console_formatter)
        self.add_handler(self._console_logger, colored_console_formatter, console_handler, CONSOLE_LOG_LEVEL)
        self.integrate_external_loggers_with_debug_logger_exclusively()

    def initialize_loggers(self):
        """
        Initialize console and debug loggers with specific settings
        """
        self._console_logger=self.create_logger("console_logger", CONSOLE_LOG_LEVEL)
        self._debug_logger=self.create_logger("debug_logger", FILE_LOG_LEVEL)
    
    def integrate_external_loggers_with_debug_logger_exclusively(self):
        """
        Integrate external library loggers to propagate their logs to the debug logger
        without showing them on the console.
        """
        for logger_name in EXTERNAL_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.INFO)  # Or any other desired log level
            logger.propagate = True  # Allow logs to propagate
            
            # Clear existing handlers to prevent duplicate logging or unwanted logging destinations
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
            
            # Add debug logger's handlers to the external loggers explicitly
            # This step ensures that logs from these libraries are directed specifically to the file handler
            # associated with our debug logger, bypassing the console logger entirely
            for handler in self._debug_logger.handlers:
                logger.addHandler(handler)

    @classmethod
    def get_console_logger(cls):
        return cls._get_instance()._console_logger

    @classmethod
    def get_debug_logger(cls):
        return cls._get_instance()._debug_logger

    @classmethod
    def _get_instance(cls, location=None):
        # Ensure the Singleton instance is created upon first access
        if location:
            return cls(location)
        else:
            return cls()

def configure_logging_directory(directory_path, knowl_folder=".knowl_logs"):
    result_dir = os.path.join(directory_path, knowl_folder)
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
    debug_logging_file_path = os.path.join(result_dir, "knowl_debug.log")
    SetupLogging().add_handlers_to_loggers(debug_logging_file_path)  # Adding handlers for Initial setup with custom log file location for debug logger