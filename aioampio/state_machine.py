"""Bridge connection state machine."""

from enum import Enum, auto


class ConnectionState(Enum):
    """Bridge connection state machine states."""

    DISCONNECTED = auto()  # Initial state, no bus connection
    CONNECTING = auto()  # Bus creation in progress
    CONNECTED = auto()  # Active session, receiving data
    RECONNECTING = auto()  # Triggered reconnect, teardown in progress
    STOPPING = auto()  # Shutdown requested
    STOPPED = auto()  # Final state, bridge stopped


class StateTransition:
    """Valid state transitions for the connection state machine."""

    # Define valid state transitions
    VALID_TRANSITIONS: dict[ConnectionState, set[ConnectionState]] = {
        ConnectionState.DISCONNECTED: {
            ConnectionState.CONNECTING,
            ConnectionState.STOPPING,
        },
        ConnectionState.CONNECTING: {
            ConnectionState.CONNECTED,
            ConnectionState.DISCONNECTED,
            ConnectionState.STOPPING,
        },
        ConnectionState.CONNECTED: {
            ConnectionState.RECONNECTING,
            ConnectionState.STOPPING,
        },
        ConnectionState.RECONNECTING: {
            ConnectionState.DISCONNECTED,
            ConnectionState.STOPPING,
        },
        ConnectionState.STOPPING: {
            ConnectionState.STOPPED,
        },
        ConnectionState.STOPPED: set(),  # Terminal state
    }

    @classmethod
    def is_valid(cls, from_state: ConnectionState, to_state: ConnectionState) -> bool:
        """Check if a state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is valid, False otherwise
        """
        return to_state in cls.VALID_TRANSITIONS.get(from_state, set())
