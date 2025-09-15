# app/mcp_tools/prompt_utils.py
from typing import Type, Dict, Any, get_origin, get_args, Union, List
from pydantic import BaseModel, Field
import inspect
import logging

from app.config import settings

logger = logging.getLogger(__name__)

def get_pydantic_model_description(model: Type[BaseModel]) -> str:
    if not inspect.isclass(model) or not issubclass(model, BaseModel):
        logger.warning(f"Provided item {model} is not a Pydantic model.")
        return ""

    model_doc = inspect.getdoc(model)
    model_title_from_config = None

    if hasattr(model, 'model_config') and isinstance(model.model_config, dict) and 'title' in model.model_config:
        model_title_from_config = model.model_config['title']
    elif hasattr(model, 'Config') and hasattr(model.Config, 'title'):
        model_title_from_config = getattr(model.Config, 'title', None)

    model_title = model_title_from_config or model.__name__
    description_parts = [f"Parameters for '{model_title}': {model_doc or 'No specific model description.'}", "Fields:"]

    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        type_name_parts = []
        is_optional = False
        actual_annotation = annotation

        origin_type = get_origin(annotation)
        if origin_type is Union:
            args_type = get_args(annotation)
            if type(None) in args_type:
                is_optional = True
                non_none_args = [arg for arg in args_type if arg is not type(None)]
                if len(non_none_args) == 1:
                    actual_annotation = non_none_args[0]
                else:
                    actual_annotation = Union[tuple(non_none_args)]

        origin_actual = get_origin(actual_annotation)
        args_actual = get_args(actual_annotation)

        if origin_actual is list or origin_actual is List:
            if args_actual and hasattr(args_actual[0], '__name__'): type_name_parts.append(f"array of {args_actual[0].__name__}")
            elif args_actual: type_name_parts.append(f"array of {repr(args_actual[0])}")
            else: type_name_parts.append("array (list)")
        elif origin_actual is dict or origin_actual is Dict:
            if args_actual and len(args_actual) == 2:
                key_type_name = args_actual[0].__name__ if hasattr(args_actual[0], '__name__') else repr(args_actual[0])
                value_type_name = args_actual[1].__name__ if hasattr(args_actual[1], '__name__') else repr(args_actual[1])
                type_name_parts.append(f"object (dictionary mapping {key_type_name} to {value_type_name})")
            else: type_name_parts.append("object (dictionary)")
        elif actual_annotation is str: type_name_parts.append("string")
        elif actual_annotation is int: type_name_parts.append("integer")
        elif actual_annotation is float: type_name_parts.append("number (float)")
        elif actual_annotation is bool: type_name_parts.append("boolean")
        elif hasattr(actual_annotation, '__name__'):
            type_name_parts.append(actual_annotation.__name__)
        else: type_name_parts.append(repr(actual_annotation))

        if is_optional: type_name_parts.insert(0, "optional")
        type_name = " ".join(type_name_parts)
        default_value_repr = "REQUIRED"
        if not field_info.is_required():
            if field_info.default is not None and field_info.default is not Ellipsis and str(field_info.default) != 'PydanticUndefined':
                default_value_repr = f"defaults to {repr(field_info.default)}"
            elif field_info.default_factory is not None:
                default_value_repr = "has a default factory if not provided"
            elif is_optional:
                 default_value_repr = "optional (defaults to null/None if not provided)"
        field_description = field_info.description or "No specific field description."
        description_parts.append(f"  - '{field_name}' (type: {type_name}, {default_value_repr}): {field_description}")
    return "\n".join(description_parts)

def get_tools_descriptions_for_llm() -> str:
    from app.mcp_tools import schemas_llm

    tools_info = "You have the following tools available to interact with the Exely hotel booking system:\n\n"
    tool_definitions = [
        {
            "tool_name_for_llm": "get_hotel_public_info",
            "model": schemas_llm.GetHotelPublicInfoParams,
            "description": f"Use this tool to get general public information about a specific hotel (default: {settings.DEFAULT_HOTEL_CODE}), such as its name, description, address, phone, services, and room types summary. Call this first if the user asks general questions about the hotel or at the beginning of the conversation to greet the user with the hotel name."
        },
        {
            "tool_name_for_llm": "get_exely_booking_options",
            "model": schemas_llm.HotelAvailabilityToolParams,
            "description": f"Use this tool to search for available hotel rooms AFTER you have identified the hotel (e.g., using get_hotel_public_info or if user specifies a new hotel). Requires check-in/out dates and number of adults. Hotel code is optional (will use default: {settings.DEFAULT_HOTEL_CODE} if not provided from previous context or user). Children ages and promocode/rate name are also optional. Default language is '{settings.DEFAULT_LANGUAGE_LLM}' and currency is '{settings.DEFAULT_CURRENCY_LLM}' if not specified by user."
        },
        {
            "tool_name_for_llm": "create_exely_reservation_and_get_link",
            "model": schemas_llm.CreateReservationToolParams,
            "description": "Use this tool to create a hotel reservation for a selected booking option. Requires 'booking_option_id' and 'guarantee_code'. Also needs full guest and customer details. This tool does not directly accept a promocode."
        },
        {
            "tool_name_for_llm": "cancel_exely_reservation",
            "model": schemas_llm.CancelReservationToolParams,
            "description": "Use this tool to cancel an existing hotel reservation. This requires the 'booking_number' and 'cancellation_code'."
        }
    ]
    for tool_def in tool_definitions:
        model_desc = get_pydantic_model_description(tool_def["model"])
        pydantic_title_from_config = None
        if hasattr(tool_def['model'], 'model_config') and isinstance(tool_def['model'].model_config, dict) and 'title' in tool_def['model'].model_config:
            pydantic_title_from_config = tool_def['model'].model_config['title']
        pydantic_title = pydantic_title_from_config or tool_def['model'].__name__
        model_desc = model_desc.replace(f"Parameters for '{pydantic_title}'", f"Parameters for tool '{tool_def['tool_name_for_llm']}'")
        tools_info += f"Tool Name: '{tool_def['tool_name_for_llm']}'\nDescription: {tool_def['description']}\n{model_desc}\n\n"
    return tools_info.strip()
