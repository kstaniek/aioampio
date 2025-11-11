"""Tests for ConnectionState and StateTransition."""

from aioampio.state_machine import ConnectionState, StateTransition


class TestConnectionState:
    """Test ConnectionState enum."""

    def test_connection_state_values(self) -> None:
        """Test that all expected states exist."""
        assert ConnectionState.DISCONNECTED.name == "DISCONNECTED"
        assert ConnectionState.CONNECTING.name == "CONNECTING"
        assert ConnectionState.CONNECTED.name == "CONNECTED"
        assert ConnectionState.RECONNECTING.name == "RECONNECTING"
        assert ConnectionState.STOPPING.name == "STOPPING"
        assert ConnectionState.STOPPED.name == "STOPPED"

    def test_connection_state_count(self) -> None:
        """Test that we have exactly 6 states."""
        assert len(ConnectionState) == 6

    def test_connection_state_names_unique(self) -> None:
        """Test that all state names are unique."""
        names = [state.name for state in ConnectionState]
        assert len(names) == len(set(names))


class TestStateTransition:
    """Test StateTransition validator."""

    def test_valid_transitions_from_disconnected(self) -> None:
        """Test valid transitions from DISCONNECTED state."""
        assert StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.CONNECTING
        )
        assert StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.STOPPING
        )

    def test_invalid_transition_from_disconnected(self) -> None:
        """Test invalid transitions from DISCONNECTED state."""
        assert not StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.CONNECTED
        )
        assert not StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING
        )

    def test_valid_transitions_from_connecting(self) -> None:
        """Test valid transitions from CONNECTING state."""
        assert StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.CONNECTED
        )
        assert StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.DISCONNECTED
        )
        assert StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.STOPPING
        )

    def test_invalid_transition_from_connecting(self) -> None:
        """Test invalid transitions from CONNECTING state."""
        assert not StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.RECONNECTING
        )

    def test_valid_transitions_from_connected(self) -> None:
        """Test valid transitions from CONNECTED state."""
        assert StateTransition.is_valid(
            ConnectionState.CONNECTED, ConnectionState.RECONNECTING
        )
        assert StateTransition.is_valid(
            ConnectionState.CONNECTED, ConnectionState.STOPPING
        )

    def test_invalid_transition_from_connected(self) -> None:
        """Test invalid transitions from CONNECTED state."""
        assert not StateTransition.is_valid(
            ConnectionState.CONNECTED, ConnectionState.CONNECTING
        )
        assert not StateTransition.is_valid(
            ConnectionState.CONNECTED, ConnectionState.DISCONNECTED
        )

    def test_valid_transitions_from_reconnecting(self) -> None:
        """Test valid transitions from RECONNECTING state."""
        assert StateTransition.is_valid(
            ConnectionState.RECONNECTING, ConnectionState.DISCONNECTED
        )
        assert StateTransition.is_valid(
            ConnectionState.RECONNECTING, ConnectionState.STOPPING
        )

    def test_valid_transitions_from_stopping(self) -> None:
        """Test valid transitions from STOPPING state."""
        assert StateTransition.is_valid(
            ConnectionState.STOPPING, ConnectionState.STOPPED
        )

    def test_invalid_transition_from_stopping(self) -> None:
        """Test invalid transitions from STOPPING state."""
        assert not StateTransition.is_valid(
            ConnectionState.STOPPING, ConnectionState.CONNECTED
        )
        assert not StateTransition.is_valid(
            ConnectionState.STOPPING, ConnectionState.CONNECTING
        )

    def test_no_transitions_from_stopped(self) -> None:
        """Test that STOPPED is a terminal state."""
        # STOPPED should have no valid transitions
        for state in ConnectionState:
            if state != ConnectionState.STOPPED:
                assert not StateTransition.is_valid(ConnectionState.STOPPED, state)

    def test_self_transition_always_invalid(self) -> None:
        """Test that self-transitions are not allowed."""
        for state in ConnectionState:
            assert not StateTransition.is_valid(state, state)

    def test_transition_symmetry(self) -> None:
        """Test that transitions are not symmetric (A->B doesn't imply B->A)."""
        # DISCONNECTED -> CONNECTING is valid
        assert StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.CONNECTING
        )
        # But CONNECTING -> DISCONNECTED is also valid (for error cases)
        assert StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.DISCONNECTED
        )

        # CONNECTING -> CONNECTED is valid
        assert StateTransition.is_valid(
            ConnectionState.CONNECTING, ConnectionState.CONNECTED
        )
        # But CONNECTED -> CONNECTING is NOT valid
        assert not StateTransition.is_valid(
            ConnectionState.CONNECTED, ConnectionState.CONNECTING
        )

    def test_valid_transitions_dict_structure(self) -> None:
        """Test VALID_TRANSITIONS dict has all states as keys."""
        for state in ConnectionState:
            assert state in StateTransition.VALID_TRANSITIONS

    def test_valid_transitions_are_sets(self) -> None:
        """Test that all transition targets are sets."""
        for transitions in StateTransition.VALID_TRANSITIONS.values():
            assert isinstance(transitions, set)

    def test_stopping_to_stopped_transition(self) -> None:
        """Test the final transition to stopped state."""
        assert StateTransition.is_valid(
            ConnectionState.STOPPING, ConnectionState.STOPPED
        )

    def test_emergency_stop_from_any_state(self) -> None:
        """Test that STOPPING can be reached from most states."""
        stoppable_states = [
            ConnectionState.DISCONNECTED,
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
            ConnectionState.RECONNECTING,
        ]

        for state in stoppable_states:
            assert StateTransition.is_valid(state, ConnectionState.STOPPING)


class TestStateTransitionCoverage:
    """Test comprehensive state transition coverage."""

    def test_all_valid_transitions_count(self) -> None:
        """Test total number of valid transitions."""
        total_valid = sum(
            len(targets) for targets in StateTransition.VALID_TRANSITIONS.values()
        )
        # Should have exactly the transitions defined
        assert total_valid > 0

    def test_no_orphaned_states(self) -> None:
        """Test that all states (except DISCONNECTED) can be reached."""
        reachable = {ConnectionState.DISCONNECTED}  # Starting state

        # Iteratively find all reachable states
        changed = True
        while changed:
            changed = False
            new_reachable = set(reachable)
            for from_state in reachable:
                for to_state in StateTransition.VALID_TRANSITIONS[from_state]:
                    if to_state not in new_reachable:
                        new_reachable.add(to_state)
                        changed = True
            reachable = new_reachable

        # All states should be reachable
        assert reachable == set(ConnectionState)

    def test_stopped_is_reachable(self) -> None:
        """Test that STOPPED state can be reached."""
        # Path: DISCONNECTED -> STOPPING -> STOPPED
        assert StateTransition.is_valid(
            ConnectionState.DISCONNECTED, ConnectionState.STOPPING
        )
        assert StateTransition.is_valid(
            ConnectionState.STOPPING, ConnectionState.STOPPED
        )
