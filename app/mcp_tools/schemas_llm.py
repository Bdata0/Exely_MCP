# app/mcp_tools/schemas_llm.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, model_validator, field_validator
from app.config import settings # Для дефолтных значений

DEFAULT_LANGUAGE_LLM = settings.DEFAULT_LANGUAGE_LLM
DEFAULT_CURRENCY_LLM = settings.DEFAULT_CURRENCY_LLM

class DialogTurn(BaseModel):
    role: str = Field(description="Role of the speaker, e.g., 'user', 'assistant', 'assistant_clarification'.")
    content: str = Field(description="Content of the message in this turn.")

class CustomerDetailLLM(BaseModel): # Ensure this exists
    model_config = {"title": "Customer (Booker) Details"}
    first_name: str = Field(description="Customer's first name.")
    last_name: str = Field(description="Customer's last name.")
    middle_name: Optional[str] = Field(None, description="Customer's middle name (optional).")
    email: str = Field(description="Customer's email address.")
    phone: str = Field(description="Customer's phone number (including country code, e.g., +995555123456).")
    comment: Optional[str] = Field(None, description="Optional comment for the reservation.")

class NlpRequestParams(BaseModel):
    model_config = {"title": "Natural Language Request Processor"}

    raw_request: str = Field(description="The raw natural language request from the user.")
    user_id: str = Field(description="The unique identifier for the user making the request.")
    dialog_history: Optional[List[DialogTurn]] = Field(
        default_factory=list,
        description="Recent turns of the conversation for context. LLM should use this to understand follow-up questions or references."
    )
    context_booking_option_id: Optional[str] = Field(
        None,
        description="[System Provided] If the user has already selected a booking option, its ID is provided here. LLM should use this for 'create_exely_reservation_and_get_link'."
    )
    context_guarantee_code: Optional[str] = Field(
        None,
        description="[System Provided] If a booking option is selected, the relevant guarantee code is provided. LLM should use this for 'create_exely_reservation_and_get_link'."
    )
    context_check_in_date: Optional[str] = Field(
        None,
        description="[System Provided] Check-in date from the current search context, if available (YYYY-MM-DD)."
    )
    context_check_out_date: Optional[str] = Field(
        None,
        description="[System Provided] Check-out date from the current search context, if available (YYYY-MM-DD)."
    )
    context_num_adults: Optional[int] = Field(
        None,
        description="[System Provided] Number of adults from the current search context, if relevant."
    )
    context_children_ages: Optional[List[int]] = Field(
        None,
        description="[System Provided] Ages of children from the current search context, if relevant."
    )
    context_hotel_info: Optional[Dict[str, Any]] = Field( # Can be a dict representation of HotelPublicInfoResult
        None,
        description="[System Provided] Public information about the current hotel (name, description, etc.), if already retrieved. LLM should use this to answer general questions and for context."
    )
    context_customer_info: Optional[Dict[str, Any]] = Field( # Added - Can be dict representation of CustomerDetailLLM
        None,
        description="[System Provided] Customer contact details (first_name, last_name, email, phone) if previously collected for booking."
    )
    current_bot_action: Optional[str] = Field( # Added
        None,
        description="[System Provided] The current action the bot is expecting from the user, e.g., 'awaiting_clarification', 'awaiting_option_choice', 'awaiting_booking_details_llm'."
    )


class HotelAvailabilityToolParams(BaseModel):
    model_config = {"title": "Hotel Availability Search"}
    hotel_code: Optional[str] = Field(
        default=None,
        description=f"Code of the hotel in Exely system. If None or not specified by user, and not in context, system will use default: {settings.DEFAULT_HOTEL_CODE}."
    )
    check_in_date: str = Field(description="Check-in date in YYYY-MM-DD format. Must be extracted or inferred from user query and current date.")
    check_out_date: str = Field(description="Check-out date in YYYY-MM-DD format. Must be extracted or inferred. Must be after check_in_date.")
    num_adults: int = Field(description="Number of adult guests.", ge=1)
    children_ages: Optional[List[int]] = Field(
        default_factory=list,
        description="Optional list of children's ages (e.g., [6, 12]). Example: If user says 'one child 7 years old', this should be [7]."
    )
    language: Optional[str] = Field(default=DEFAULT_LANGUAGE_LLM, description=f"Language for the search results (e.g., 'en-gb', 'ru-ru'). Default: {DEFAULT_LANGUAGE_LLM}.")
    currency: Optional[str] = Field(default=DEFAULT_CURRENCY_LLM, description=f"Preferred currency for prices (e.g., 'USD', 'EUR', 'GEL'). Default: {DEFAULT_CURRENCY_LLM}.")
    promocode_or_rate_name: Optional[str] = Field(
        default=None,
        description="Optional. If the user provides a promocode or a specific rate plan name, provide it here. The system will try to find and apply this rate."
    )

class GuestDetailLLM(BaseModel):
    model_config = {"title": "Guest Details"}
    first_name: str = Field(description="Guest's first name.")
    last_name: str = Field(description="Guest's last name.")
    middle_name: Optional[str] = Field(None, description="Guest's middle name (optional).")
    citizenship: Optional[str] = Field(None, description="Guest's citizenship ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB', 'GE') (optional).")
    is_child: bool = Field(default=False, description="Set to true if this guest is a child. If true, 'age' is required.")
    age: Optional[int] = Field(None, description="Age of the child in years. Required if is_child is true. Must be one of the ages provided in the initial search if any.")

    @model_validator(mode='after')
    def check_child_age(cls, values):
        is_child = getattr(values, 'is_child', False)
        age = getattr(values, 'age', None)
        if is_child and age is None:
            raise ValueError("Age is required if is_child is true.")
        return values

class CreateReservationToolParams(BaseModel):
    model_config = {"title": "Hotel Reservation Creation"}
    booking_option_id: str = Field(description="The unique ID of the booking option selected by the user from prior search results. This is CRITICAL and MUST be present (system provides this in context after user selects an option).")
    guests: List[GuestDetailLLM] = Field(description="A list containing details for EACH guest who will be staying (first_name, last_name are mandatory for each). Total number of guests must match the original search request for the selected option.")
    customer: CustomerDetailLLM = Field(description="Details of the person making the booking (first_name, last_name, email, phone are mandatory).")
    guarantee_code: str = Field(description="The code of the selected guarantee/payment method for this booking option. This is CRITICAL and MUST be present (system provides this in context after option selection).")
    language: Optional[str] = Field(default=DEFAULT_LANGUAGE_LLM, description=f"Language for the reservation process and notifications. Default: {DEFAULT_LANGUAGE_LLM}.")

class CancelReservationToolParams(BaseModel):
    model_config = {"title": "Reservation Cancellation"}
    booking_number: str = Field(description="The reservation number to be cancelled. This should have been provided to the user when the booking was made.")
    cancellation_code: str = Field(description="The cancellation code for the reservation. This should have been provided to the user when the booking was made.")
    language: Optional[str] = Field(default=DEFAULT_LANGUAGE_LLM, description=f"Language for the API response. Default: {DEFAULT_LANGUAGE_LLM}.")
    reason_code: Optional[str] = Field(default="cancellation_travel", description="Optional code for the cancellation reason (e.g., 'cancellation_travel', 'custom'). Default: 'cancellation_travel'.")
    reason_text: Optional[str] = Field(None, description="Optional text for the cancellation reason, especially if reason_code is 'custom'.")

class BookingOptionResult(BaseModel):
    option_id: str = Field(description="Unique identifier for this booking option.")
    summary_text: str = Field(description="A human-readable summary of the room, rate, price, and cancellation policy.")
    details: Dict[str, Any] = Field(description="Detailed information about the option, including price, currency, room/rate codes, cancellation policy, available guarantee methods, hotel name, room name and room images.")

class CreateReservationResult(BaseModel):
    booking_number: str = Field(description="The booking number if successful, otherwise empty.")
    status: str = Field(description="The status of the reservation (e.g., 'confirmed', 'pending_payment', 'error').")
    cancellation_code: str = Field(description="The cancellation code if successful, otherwise empty.")
    payment_url: Optional[str] = Field(None, description="URL for payment if required, otherwise null.")
    order_url: Optional[str] = Field(None, description="URL to view the order details if available, otherwise null.")
    error_message: Optional[str] = Field(None, description="Error message if the reservation failed, otherwise null.")
    details_api_errors: Optional[List[Dict[str, Any]]] = Field(None, description="For debugging: detailed API errors if DEBUG_MODE is on.")

class CancelReservationResult(BaseModel):
    booking_number: str = Field(description="The booking number that was attempted to be cancelled.")
    status: str = Field(description="The status of the reservation after the cancellation attempt (e.g., 'cancelled', 'error_api', 'unchanged').")
    message: str = Field(description="A message describing the result of the cancellation attempt.")
    error_details: Optional[Any] = Field(None, description="For debugging: detailed API error information if any.")


class GetHotelPublicInfoParams(BaseModel):
    model_config = {"title": "Get Hotel Public Information"}
    hotel_code: str = Field(description=f"The code of the hotel. For default hotel, use '{settings.DEFAULT_HOTEL_CODE}'.")
    language: Optional[str] = Field(default=DEFAULT_LANGUAGE_LLM, description=f"Language for the information. Default: {DEFAULT_LANGUAGE_LLM}.")

class HotelPublicInfoResult(BaseModel):
    model_config = {"title": "Hotel Public Information"}
    hotel_code: str
    name: Optional[str] = None
    description: Optional[str] = None
    stars: Optional[float] = None
    logo_url: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    check_in_time: Optional[str] = None
    check_out_time: Optional[str] = None
    services_summary: Optional[List[str]] = Field(default_factory=list, description="A list of key service names or categories available.")
    room_types_summary: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Summary of room types with name and code.")
    raw_hotel_details_for_context: Optional[Dict[str, Any]] = Field(default=None, exclude=True)
