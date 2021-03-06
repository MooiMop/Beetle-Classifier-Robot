import time
import pyvisa
from sys import platform

try:
    import Modules.tools as tools
except ModuleNotFoundError:
    import tools


class ESP():
    READ_TERMINATION = '\r'
    WRITE_TERMINATION = '\r'
    TIMEOUT = 60000  # milliseconds

    def __init__(self, name, identifiers: list, testflight=False):
        self.testflight = testflight

        if testflight:
            tools.logprint(f'Initializing {tools.bcolors.yellow("fictional")} '
                           'connection with ESP.')
            self.instruments = ['fake instrument'] * len(identifiers)

        elif platform != "win32":
            tools.logprint('Not running on Windows platform. Turning on '
                           'testflight mode.', 'yellow')
            self.testflight = True
            self.instruments = ['fake instrument'] * len(identifiers)

        else:
            self.rm = pyvisa.ResourceManager()
            self.instruments = self.connect(identifiers, self.list_devices())

    def list_devices(self):
        if not self.testflight:
            devices = self.rm.list_resources()
            tools.logprint(f'Resource manager used:     {self.rm}')
            tools.logprint(f'Detected devices:          {devices}')
            return devices

    def connect(self, identifiers, devices):
        if not self.testflight:
            tools.logprint('Initializing new connections with ESP '
                           f'with identifiers:      {identifiers}.')

            instruments = []
            for identifier in identifiers:
                # Find first match in list of connected devices.
                if identifier in '\t'.join(devices):
                    match = next(filter(
                        lambda device: identifier in device, devices), None)
                    instrument = self.rm.open_resource(match)

                    # Set universal ESP300 parameters
                    instrument.read_termination = self.READ_TERMINATION
                    instrument.write_termination = self.WRITE_TERMINATION
                    instrument.timeout = self.TIMEOUT
                    instruments.append(instrument)

                else:
                    tools.logprint(f'Cannot find device with id {identifier}',
                                   'red')
            return instruments

    def __del__(self):
        if not self.testflight:
            for instrument in self.instruments:
                tools.logprint(f'Disconnecting {instrument}', 'yellow')
                instrument.close()
            tools.logprint(f'Disconnecting resource manager', 'yellow')
            self.rm.close()


class Motor():
    COMMANDS = {
        'define home': 'DH',
        'move to absolute position': 'PA',
        'move to relative position': 'PR',
        'read error code': 'TE?',
        'search for home': 'OR',
        'set home search mode': 'OM',
        'set velocity': 'VA',
        'wait for motion stop': 'WS',
    }
    ERROR_CODES = {
        '1': 'PCI COMMUNICATION TIME-OUT',
        '7': 'PARAMETER OUT OF RANGE',
        '9': 'AXIS NUMBER OUT OF RANGE',
        '10': 'MAXIMUM VELOCITY EXCEEDED',
        '13': 'MOTOR NOT ENABLED',
        '37': 'AXIS NUMBER MISSING',
        '38': 'COMMAND PARAMETER MISSING'
    }

    def __init__(self, name, instrument, axis, bounds=[-180, 180], velocity=4,
                 testflight=False):

        # Convert supplied parameters to their 'self' equivalents.
        for key in dir():
            if 'self' not in key:
                self.__setattr__(key, eval(key))
        if testflight:
            self.current_position = 0.0
        else:
            self.send_command('set velocity', velocity)
            self.send_command('set home search mode', 0)

    def define_home(self, degrees=0):
        tools.logprint('New home sequence! \n', 'yellow')
        print(f'You are about to redefine current position '
              f' {self.get_current_position()} as {degrees}.')
        choice = input('Are you sure you want to make this change? (Y/N)')
        if choice in ['Y', 'y']:
            if self.send_command('define home', degrees):
                tools.logprint('New home position saved.', 'green')
            else:
                tools.logprint('Failed to set new home position.', 'red')

    def get_current_position(self):
        if self.testflight:
            return self.current_position
        else:
            return float(self.instrument.query(str(self.axis)+'TP?')[:-1])

    def move(self, degrees, mode='relative', verbose=True):
        if mode == 'absolute':
            new_position = degrees
        elif mode == 'relative':
            new_position = self.get_current_position() + degrees

        allowed = self.bounds[0] <= new_position <= self.bounds[1]
        if allowed:
            if verbose:
                tools.logprint(f'Moving axis {self.axis} to position '
                               f'{new_position} degrees.')
            self.send_command('move to absolute position', new_position)
        else:
            tools.logprint(f'Desired position {new_position} is out of '
                           f'operating bounds of axis {self.axis}.', 'red')

    def send_ASCII_command(self, command):
        if self.testflight:
            return True
        else:
            self.instrument.write(command)
            err = self.instrument.query(self.COMMANDS['read error code'])
            if err[0] == str(self.axis) and len(err) > 2:
                err = err[1:]
            if err != '0':
                if err in self.ERROR_CODES:
                    tools.logprint(
                        f'Error code {err}: {self.ERROR_CODES[err]}', 'red')
                else:
                    tools.logprint(f'Error code {err}', 'red')
                return False
            else:
                return True

    def send_command(self, command, parameter=''):
        if self.testflight:
            return True
        else:
            time.sleep(1)
            full_command = f'{self.axis}{self.COMMANDS[command]}{parameter}'
            if 'move' in command:
                wait = f'{self.axis}{self.COMMANDS["wait for motion stop"]}0'
                full_command += ';' + wait

            self.write_command(full_command)
            err = self.query_command(self.COMMANDS['read error code'])
            # remove first number from error code if the first number is the
            # same as the axis number.
            if err[0] == str(self.axis) and len(err) > 2:
                err = err[1:]
            if err != '0':
                if err in self.ERROR_CODES:
                    tools.logprint(
                        f'Error code {err}: {self.ERROR_CODES[err]} on device '
                        f'"{self.name}" while executing command '
                        f'"{full_command}".', 'red')
                else:
                    tools.logprint(
                        f'Error code {err} on device {self.name}.',
                        'red')
                return False
            else:
                return True

    def write_command(self, command, attempt=1):
        try:
            self.instrument.write(command)
        except pyvisa.VisaIOError:
            tools.logprint(
                f'Got a VisaIOError on device "{self.name}" while '
                f' executing command "{command}" (attempt {attempt}).',
                'red')
            if attempt < 3:
                self.write_command(command, attempt=attempt + 1)
            else:
                tools.logprint('Three attempts failed. Will continue with '
                               'next command.', 'red')
                return 'VisaIOError'

    def query_command(self, command, attempt=1):
        try:
            output = self.instrument.query(command)
        except pyvisa.VisaIOError:
            tools.logprint(
                f'Got a VisaIOError on device "{self.name}" while '
                f' executing command "{command}" (attempt {attempt}).',
                'red')
            if attempt < 3:
                output = self.query_command(command, attempt=attempt + 1)
            else:
                tools.logprint('Three attempts failed. Will continue with '
                               'next command.', 'red')
                return 'VisaIOError'
        return output

class Polarizer():

    def __init__(self, name, inst1, inst2, ax1, ax2, bounds=[-410, 410],
                 velocity=20, testflight=False):
        ''' 1 is linear polarizer, 2 is lambda/4 plate
        '''

        self.lin_polarizer = Motor(
            'linear polarizer', inst1, ax1, bounds, velocity, testflight)
        self.quart_lambda = Motor(
            'quarter wave plate', inst2, ax2, bounds, velocity, testflight)

    def set(self, degrees, verbose=True):
        '''Hardware definitions:
        linear polarizer: 0 degrees = vertical / S / Perpendicular
        lambda/4 plate: 0 degrees = horizontal
        '''
        self.lin_polarizer.move(degrees, 'absolute', verbose)
        p = self.lin_polarizer.get_current_position()
        self.quart_lambda.move(p + 45, 'absolute', verbose)


if __name__ == '__main__':
    None
