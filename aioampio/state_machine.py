"""Bridge connection state machine.

This module defines the connection state machine for the Ampio bridge,
including valid states and state transitions. The state machine ensures
that the bridge connection lifecycle follows a predictable pattern and
prevents invalid state transitions.

State Flow:
    DISCONNECTED -> CONNECTING -> CONNECTED -> RECONNECTING -> DISCONNECTED
                 |            |             |
                 v            v             v
              STOPPING ->  STOPPING ->  STOPPING -> STOPPED

The state machine provides:
- Clear connection lifecycle semantics
- Prevention of invalid state transitions
- Easy monitoring of connection status
- Consistent error handling patterns

Classes:
    ConnectionState: Enum of possible connection states
    StateTransition: Validator for state machine transitions

Example:
    >>> state = ConnectionState.DISCONNECTED
    >>> can_connect = StateTransition.is_valid(state, ConnectionState.CONNECTING)
    >>> print(can_connect)
    True
"""

from enum import Enum, auto


class ConnectionState(Enum):
    """Bridge connection state machine states.

    This enum defines the possible states for the bridge connection lifecycle.
    Each state represents a specific point in the connection flow.

    States:
        DISCONNECTED: Initial state with no active bus connection
        CONNECTING: Bus creation and connection in progress
        CONNECTED: Active session with data flow
        RECONNECTING: Triggered reconnect, teardown in progress
        STOPPING: Graceful shutdown requested
        STOPPED: Final terminal state, bridge completely stopped

    Note:
        STOPPED is a terminal state with no outgoing transitions.
    """

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
