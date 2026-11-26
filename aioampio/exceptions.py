"""Public errors raised by Ampio operations."""


class AmpioTransmissionError(ConnectionError):
    """A CAN frame could not be submitted to the transport."""
