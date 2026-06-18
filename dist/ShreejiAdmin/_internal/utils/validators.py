"""
Business logic validators for the Garage Management System.
Provides centralized validation for status transitions and booking rules.
"""

from utils.constants import (
    STATUS_APPROVED,
    STATUS_CHECKED_IN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_REJECTED,
)

VALID_STATUS_TRANSITIONS = {
    STATUS_PENDING: [STATUS_APPROVED, STATUS_REJECTED],
    STATUS_APPROVED: [STATUS_CHECKED_IN],
    STATUS_CHECKED_IN: [STATUS_COMPLETED],
    STATUS_COMPLETED: [],
    STATUS_REJECTED: [],
}

STATUS_DISPLAY_NAMES = {
    STATUS_PENDING: "Pending",
    STATUS_APPROVED: "Approved",
    STATUS_CHECKED_IN: "Checked In",
    STATUS_COMPLETED: "Completed",
    STATUS_REJECTED: "Rejected",
}


def is_valid_status_transition(current_status, new_status):
    """
    Validate if a status transition is allowed.
    
    Args:
        current_status: The current booking status
        new_status: The desired new status
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    current = (current_status or STATUS_PENDING).lower().strip()
    new = (new_status or "").lower().strip()
    
    if not new:
        return False, "New status is required."
    
    if current == new:
        return False, f"Booking is already {STATUS_DISPLAY_NAMES.get(current, current)}."
    
    allowed_transitions = VALID_STATUS_TRANSITIONS.get(current, [])
    
    if new not in allowed_transitions:
        current_display = STATUS_DISPLAY_NAMES.get(current, current.title())
        new_display = STATUS_DISPLAY_NAMES.get(new, new.title())
        
        if current in (STATUS_COMPLETED, STATUS_REJECTED):
            return False, (
                f"Cannot change status from {current_display}. "
                f"This booking is already finalized."
            )
        
        allowed_names = [
            STATUS_DISPLAY_NAMES.get(s, s.title()) 
            for s in allowed_transitions
        ]
        allowed_str = ", ".join(allowed_names) if allowed_names else "none"
        
        return False, (
            f"Cannot change status from {current_display} to {new_display}. "
            f"Allowed transitions: {allowed_str}."
        )
    
    return True, None


def get_allowed_next_statuses(current_status):
    """
    Get list of valid next statuses for a given current status.
    
    Args:
        current_status: The current booking status
        
    Returns:
        list: Valid next status strings
    """
    current = (current_status or STATUS_PENDING).lower().strip()
    return VALID_STATUS_TRANSITIONS.get(current, [])


def can_perform_action(current_status, action):
    """
    Check if a specific action can be performed on a booking.
    
    Args:
        current_status: The current booking status
        action: The action to perform ('approve', 'reject', 'checkin', 'complete')
        
    Returns:
        bool: True if action is allowed
    """
    current = (current_status or STATUS_PENDING).lower().strip()
    action = (action or "").lower().strip()
    
    action_to_status = {
        "approve": STATUS_APPROVED,
        "reject": STATUS_REJECTED,
        "checkin": STATUS_CHECKED_IN,
        "complete": STATUS_COMPLETED,
    }
    
    target_status = action_to_status.get(action)
    if not target_status:
        return False
    
    is_valid, _ = is_valid_status_transition(current, target_status)
    return is_valid
