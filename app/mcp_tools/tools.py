# app/mcp_tools/tools.py

import uuid
from typing import List, Dict, Any, Optional, Union
import logging
from datetime import datetime, timedelta
from pydantic import BaseModel, ValidationError
import json

from app.config import settings
from app.exely_client.client import ExelyDistributionApiClient, ExelyApiException
from app.exely_client.schemas import (
    HotelAvailabilityRequestParams, HotelAvailabilityCriterion,
    HotelAvailabilityCriterionHotel, HotelRef as ExelyHotelRef,
    HotelAvailabilityResponse, RoomStayAvailability, RatePlanAvailabilityInfo,
    GuestPlacementRef,
    HotelReservationRequest, HotelReservationRequestItem, RoomStayReservation,
    RoomTypeReservation, RoomTypeReservationPlacement, RatePlanReservation,
    GuestInfo as ExelyGuestInfoAPI,
    GuestCountInfoAPI as ExelyGuestCountInfoAPI,
    GuestCountDetailAPI as ExelyGuestCountDetailAPI,
    CustomerReservation as ExelyCustomerReservationAPI,
    CustomerContactInfo as ExelyCustomerContactInfoAPI,
    CustomerContactPhone as ExelyCustomerContactPhoneAPI,
    CustomerContactEmail as ExelyCustomerContactEmailAPI,
    GuaranteeReservation as ExelyGuaranteeReservationAPI,
    PointOfSale as ExelyPointOfSaleAPI,
    CancelReservationRequestPayload, CancelHotelReservationRef,
    CancelReservationVerification, CancelReservationReason,
    HotelInfoResponse, HotelInfoHotelDetail, HotelRatePlanDetail,
    ImageDetail as ExelyImageDetail
)
from .schemas_llm import (
    HotelAvailabilityToolParams, CreateReservationToolParams, GuestDetailLLM, CustomerDetailLLM,
    BookingOptionResult, CreateReservationResult,
    CancelReservationToolParams, CancelReservationResult,
    NlpRequestParams, DialogTurn,
    GetHotelPublicInfoParams, HotelPublicInfoResult
)
from app.llm_client.llm_client import get_llm_response
from .prompt_utils import get_tools_descriptions_for_llm


logger = logging.getLogger(__name__)

BOOKING_OPTIONS_CACHE: Dict[str, RoomStayAvailability] = {}
HOTEL_INFO_CACHE: Dict[str, Dict[str, Any]] = {}

def get_exely_client() -> ExelyDistributionApiClient:
    return ExelyDistributionApiClient(api_key=settings.EXELY_API_KEY, base_url=settings.EXELY_BASE_URL)

async def get_hotel_details_from_api(hotel_code: str, language: str) -> Optional[HotelInfoHotelDetail]:
    # ... (код этой функции без изменений, как в предыдущем ответе) ...
    cached_entry = HOTEL_INFO_CACHE.get(hotel_code)
    if cached_entry:
        cached_at_ts = cached_entry.get("_cached_at_ts")
        if isinstance(cached_at_ts, float) and (datetime.now().timestamp() - cached_at_ts) < 3600: # Кэш на 1 час
            logger.debug(f"Использование кэшированной информации для отеля {hotel_code}")
            data_to_parse = cached_entry.copy()
            data_to_parse.pop("_cached_at_ts", None)
            try:
                return HotelInfoHotelDetail.model_validate(data_to_parse)
            except ValidationError as ve:
                logger.error(f"Ошибка валидации кэшированных данных для HotelInfoHotelDetail (отель {hotel_code}): {ve}")
                HOTEL_INFO_CACHE.pop(hotel_code, None)
            except Exception as e_val_cache:
                 logger.error(f"Неожиданная ошибка при валидации кэша для HotelInfoHotelDetail (отель {hotel_code}): {e_val_cache}")
                 HOTEL_INFO_CACHE.pop(hotel_code, None)
        else:
            logger.info(f"Кэш для отеля {hotel_code} устарел или отсутствует/некорректна метка времени.")
            HOTEL_INFO_CACHE.pop(hotel_code, None)

    client = get_exely_client()
    try:
        logger.info(f"Запрос информации hotel_info для отеля {hotel_code} на языке {language}")
        hotel_info_raw = await client.get_hotel_info(hotel_code=hotel_code, language=language)

        if hotel_info_raw and hotel_info_raw.get("hotels"):
            hotel_detail_data = hotel_info_raw["hotels"][0]
            try:
                hotel_detail_obj = HotelInfoHotelDetail.model_validate(hotel_detail_data)
                data_to_cache = hotel_detail_obj.model_dump(exclude_none=True)
                data_to_cache["_cached_at_ts"] = datetime.now().timestamp()
                HOTEL_INFO_CACHE[hotel_code] = data_to_cache
                logger.info(f"Информация для отеля {hotel_code} ({hotel_detail_obj.name or 'имя не найдено'}) получена и кэширована.")
                return hotel_detail_obj
            except ValidationError as ve:
                logger.error(f"Ошибка валидации HotelInfoHotelDetail для отеля {hotel_code}: {ve.errors(include_url=False)}", exc_info=True)
                logger.debug(f"Данные, не прошедшие валидацию: {json.dumps(hotel_detail_data, indent=2, ensure_ascii=False)}")
                return None
        else:
            logger.warning(f"Ответ hotel_info для отеля {hotel_code} не содержит данных в поле 'hotels' или ответ пуст.")
            return None
    except ExelyApiException as e:
        logger.error(f"API Exception при получении hotel_info для отеля {hotel_code}: {str(e)}", exc_info=settings.DEBUG_MODE)
        return None
    except Exception as e_generic:
        logger.error(f"Неожиданная ошибка при получении hotel_info для отеля {hotel_code}: {e_generic}", exc_info=True)
        return None
    finally:
        await client.close()

async def get_hotel_public_info(params: GetHotelPublicInfoParams) -> HotelPublicInfoResult:
    # ... (код этой функции без изменений) ...
    logger.info(f"Выполнение инструмента: 'get_hotel_public_info' для отеля {params.hotel_code}")
    hotel_details: Optional[HotelInfoHotelDetail] = await get_hotel_details_from_api(
        hotel_code=params.hotel_code,
        language=params.language or settings.DEFAULT_LANGUAGE_LLM
    )

    if not hotel_details:
        logger.warning(f"Не удалось получить детали для отеля {params.hotel_code} через get_hotel_details_from_api.")
        return HotelPublicInfoResult(hotel_code=params.hotel_code, name=f"Информация об отеле {params.hotel_code} не найдена")

    address_parts = []
    if hotel_details.contact_info and hotel_details.contact_info.addresses:
        addr = hotel_details.contact_info.addresses[0]
        if addr.address_line: address_parts.extend(addr.address_line)
        if addr.city_name: address_parts.append(addr.city_name)
        if addr.postal_code: address_parts.append(addr.postal_code)
        if addr.country_code: address_parts.append(f"({addr.country_code})")

    phone_number = None
    if hotel_details.contact_info and hotel_details.contact_info.phones:
        phone_number = hotel_details.contact_info.phones[0].phone_number

    services_summary = []
    if hotel_details.services:
        for service in hotel_details.services[:7]: # Limit to 7 services
            if service.name:
                services_summary.append(service.name)

    room_types_summary = []
    if hotel_details.room_types:
        for rt in hotel_details.room_types[:5]: # Limit to 5 room types
            if rt.name and rt.code:
                rt_info: Dict[str, Any] = {"name": rt.name, "code": rt.code}
                if rt.size and rt.size.value:
                    rt_info["size"] = f"{rt.size.value} {rt.size.unit}"
                room_types_summary.append(rt_info)

    raw_details_dict = hotel_details.model_dump(exclude_none=True)

    return HotelPublicInfoResult(
        hotel_code=hotel_details.code, name=hotel_details.name,
        description=hotel_details.description, stars=hotel_details.stars,
        logo_url=str(hotel_details.logo.url) if hotel_details.logo else None,
        address=", ".join(address_parts) if address_parts else None, phone=phone_number,
        check_in_time=hotel_details.policy.check_in_time if hotel_details.policy else None,
        check_out_time=hotel_details.policy.check_out_time if hotel_details.policy else None,
        services_summary=services_summary if services_summary else None,
        room_types_summary=room_types_summary if room_types_summary else None,
        raw_hotel_details_for_context=raw_details_dict # This is important for context
    )

async def get_exely_booking_options(params: HotelAvailabilityToolParams) -> List[BookingOptionResult]:
    # ... (код этой функции без изменений) ...
    logger.info(f"Выполнение инструмента Exely: 'get_exely_booking_options'.")
    if settings.DEBUG_MODE:
        logger.debug(f"Параметры для get_exely_booking_options:\n{params.model_dump_json(indent=2, exclude_none=True)}")

    hotel_code_to_search = params.hotel_code or settings.DEFAULT_HOTEL_CODE
    language_to_use = params.language or settings.DEFAULT_LANGUAGE_LLM
    promocode_or_rate_name_query = params.promocode_or_rate_name

    hotel_details: Optional[HotelInfoHotelDetail] = await get_hotel_details_from_api(hotel_code_to_search, language_to_use)

    hotel_name_for_summary = hotel_details.name if hotel_details and hotel_details.name else f"Отель {hotel_code_to_search}"
    room_type_images_map: Dict[str, List[str]] = {}
    rate_plan_details_map: Dict[str, HotelRatePlanDetail] = {}

    if hotel_details:
        if hotel_details.room_types:
            for rt_detail in hotel_details.room_types:
                if rt_detail.code and rt_detail.images:
                    room_type_images_map[rt_detail.code] = [str(img.url) for img in rt_detail.images]
        if hotel_details.rate_plans:
            for rp_detail in hotel_details.rate_plans:
                if rp_detail.code:
                    rate_plan_details_map[rp_detail.code] = rp_detail
    else:
        logger.warning(f"Не удалось получить hotel_info для отеля {hotel_code_to_search}. Поиск доступности может быть неполным.")


    client = get_exely_client()
    children_ages_str: Optional[str] = None
    if params.children_ages and isinstance(params.children_ages, list):
        children_ages_str = ",".join(map(str, params.children_ages))

    try:
        check_in_dt = datetime.strptime(params.check_in_date, '%Y-%m-%d')
        check_out_dt = datetime.strptime(params.check_out_date, '%Y-%m-%d')
        if check_out_dt <= check_in_dt: raise ValueError("Дата выезда должна быть после даты заезда.")
        today_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if check_in_dt < today_midnight:
             raise ValueError("Дата заезда не может быть в прошлом.")
    except ValueError as ve:
        logger.error(f"Неверный формат даты или логика для поиска доступности: {ve}. Параметры: {params.model_dump_json()}")
        return [BookingOptionResult(option_id="error", summary_text=f"Предоставлены неверные даты: {ve}", details={"error": str(ve), "reason": str(ve)})]

    criterion = HotelAvailabilityCriterion(
        ref="0",
        hotels=[HotelAvailabilityCriterionHotel(code=hotel_code_to_search)],
        dates=f"{params.check_in_date};{params.check_out_date}",
        adults=params.num_adults,
        children=children_ages_str
    )
    request_params_exely = HotelAvailabilityRequestParams(
        language=language_to_use,
        currency=params.currency or settings.DEFAULT_CURRENCY_LLM,
        criterions=[criterion], include_rates=True, include_transfers=False,
        include_all_placements=True, include_promo_restricted=True
    )

    try:
        response: HotelAvailabilityResponse = await client.get_hotel_availability(request_params_exely)
    except ExelyApiException as e:
        logger.error(f"API Exception в get_exely_booking_options: {str(e)}", exc_info=settings.DEBUG_MODE)
        api_details_for_error = e.error_response if isinstance(e.error_response, dict) else {"raw_error": str(e.error_response)}
        return [BookingOptionResult(option_id="error", summary_text=f"Поиск не удался из-за проблемы с API: {str(e)}", details={"error": str(e), "reason": "api_issue", "details_api": api_details_for_error})]
    finally:
        await client.close()

    if response.errors:
        specific_error_reason_for_llm = "; ".join([err.message or f"API ошибка (код: {err.error_code})" for err in response.errors])
        logger.warning(f"get_exely_booking_options - API вернул ошибки: {specific_error_reason_for_llm}")
        return [BookingOptionResult(option_id="error", summary_text=f"Поиск не удался: {specific_error_reason_for_llm}", details={"error_api": [err.model_dump() for err in response.errors], "reason": specific_error_reason_for_llm})]

    processed_room_stays: List[RoomStayAvailability] = []
    if promocode_or_rate_name_query and response.room_stays:
        logger.info(f"Применяется фильтр по промокоду/имени тарифа: '{promocode_or_rate_name_query}'")
        query_lower = promocode_or_rate_name_query.lower()
        for room_stay_candidate in response.room_stays:
            matching_rate_plans_in_stay: List[RatePlanAvailabilityInfo] = []
            if not room_stay_candidate.rate_plans:
                logger.debug(f"  RoomStay для типа {room_stay_candidate.room_types[0].code if room_stay_candidate.room_types else 'N/A'} не имеет rate_plans, пропускается.")
                continue
            for rp_avail_info in room_stay_candidate.rate_plans:
                rp_detail_from_hotel_info = rate_plan_details_map.get(rp_avail_info.code)
                match_found = False
                if rp_detail_from_hotel_info:
                    if rp_detail_from_hotel_info.code.lower() == query_lower:
                        match_found = True
                        logger.debug(f"  Тариф совпал по КОДУ: '{rp_detail_from_hotel_info.code}' с запросом '{promocode_or_rate_name_query}'")
                    elif rp_detail_from_hotel_info.name and rp_detail_from_hotel_info.name.lower() == query_lower:
                        match_found = True
                        logger.debug(f"  Тариф совпал по ИМЕНИ: '{rp_detail_from_hotel_info.name}' с запросом '{promocode_or_rate_name_query}'")
                if match_found:
                    matching_rate_plans_in_stay.append(rp_avail_info)
            if matching_rate_plans_in_stay:
                filtered_placement_rates = [
                    pr for pr in room_stay_candidate.placement_rates
                    if pr.rate_plan_code in [mrp.code for mrp in matching_rate_plans_in_stay]
                ]
                if filtered_placement_rates:
                    new_room_stay = room_stay_candidate.model_copy(deep=True)
                    new_room_stay.rate_plans = matching_rate_plans_in_stay
                    new_room_stay.placement_rates = filtered_placement_rates
                    processed_room_stays.append(new_room_stay)
                    logger.info(f"  RoomStay для типа {new_room_stay.room_types[0].code if new_room_stay.room_types else 'N/A'} сохранен с отфильтрованными тарифами.")
                else:
                    logger.info(f"  RoomStay для типа {room_stay_candidate.room_types[0].code if room_stay_candidate.room_types else 'N/A'} отброшен: после фильтрации тарифов не осталось цен (placement_rates).")
            else:
                 logger.info(f"  RoomStay для типа {room_stay_candidate.room_types[0].code if room_stay_candidate.room_types else 'N/A'} отброшен: нет тарифов, совпадающих с '{promocode_or_rate_name_query}'.")
        if not processed_room_stays:
            no_promo_msg = f"Для отеля '{hotel_name_for_summary}' по вашему запросу с учетом промокода/тарифа '{promocode_or_rate_name_query}' не найдено доступных вариантов."
            logger.info(no_promo_msg)
            return [BookingOptionResult(option_id="no_options_promo", summary_text=no_promo_msg, details={"reason": "no_availability_with_promo", "hotel_name": hotel_name_for_summary})]
    elif response.room_stays:
        processed_room_stays = response.room_stays
    else:
        no_rooms_msg = f"Для отеля '{hotel_name_for_summary}' на выбранные критерии нет доступных номеров."
        reason_for_details = "no_availability"
        if response.warnings:
            hotel_not_found_warning = next((w.message for w in response.warnings if w.message and ("not found" in w.message.lower() or w.error_code == "392")), None)
            if hotel_not_found_warning:
                no_rooms_msg = f"Поиск не удался: {hotel_not_found_warning} (Отель: {hotel_code_to_search})"
                reason_for_details = hotel_not_found_warning
            else:
                first_warning_msg = response.warnings[0].message or f"API предупреждение (код: {response.warnings[0].error_code})"
                no_rooms_msg = f"Для отеля '{hotel_name_for_summary}' нет доступных номеров. Примечание: {first_warning_msg}"
                reason_for_details = first_warning_msg
        logger.info(f"get_exely_booking_options - Не найдены варианты размещения. Сообщение: '{no_rooms_msg}'")
        return [BookingOptionResult(option_id="no_options", summary_text=no_rooms_msg, details={"reason": reason_for_details, "hotel_name": hotel_name_for_summary})]

    options_results: List[BookingOptionResult] = []
    requested_total_guests = params.num_adults + len(params.children_ages or [])
    for i, room_stay in enumerate(processed_room_stays):
        option_id = str(uuid.uuid4())
        actual_capacity_of_room_stay = sum(g.count for g in room_stay.guests) if room_stay.guests else 0
        rt_code = room_stay.room_types[0].code if room_stay.room_types else "N/A"
        if not room_stay.rate_plans:
            logger.info(f"  Пропуск RoomStay (индекс {i}), так как после фильтрации по промокоду не осталось тарифов.")
            continue
        rp_code = room_stay.rate_plans[0].code
        if settings.DEBUG_MODE:
            logger.debug(f"  Обработка отфильтрованного RoomStay {i}: Отель={room_stay.hotel_ref.code}, ТипНом={rt_code}, Тариф={rp_code}. "
                         f"Факт. вместимость: {actual_capacity_of_room_stay}. Запрошено гостей: {requested_total_guests}.")
        if actual_capacity_of_room_stay < requested_total_guests:
            logger.info(f"  Пропуск отфильтрованного RoomStay {i} (Отель={room_stay.hotel_ref.code}, ТипНом={rt_code}) так как его вместимость ({actual_capacity_of_room_stay}) меньше запрошенной ({requested_total_guests}).")
            continue
        BOOKING_OPTIONS_CACHE[option_id] = room_stay
        room_type_name_from_details = rt_code
        if hotel_details and hotel_details.room_types:
            found_rt = next((rt for rt in hotel_details.room_types if rt.code == rt_code), None)
            if found_rt and found_rt.name: room_type_name_from_details = found_rt.name
        rate_plan_name_from_details = rp_code
        applied_promo_info = ""
        if rp_code in rate_plan_details_map:
            rate_plan_name_from_details = rate_plan_details_map[rp_code].name or rp_code
            if promocode_or_rate_name_query and (rate_plan_name_from_details.lower() == promocode_or_rate_name_query.lower() or rp_code.lower() == promocode_or_rate_name_query.lower()):
                applied_promo_info = f" (тариф '{rate_plan_name_from_details}' применен)"
        room_type_display = f"Тип номера '{room_type_name_from_details}' (код {rt_code})"
        rate_plan_display = f"Тариф '{rate_plan_name_from_details}' (код {rp_code}){applied_promo_info}"
        price_display = f"{room_stay.total.price_after_tax:.2f} {room_stay.total.currency}"
        cancellation_policy = room_stay.rate_plans[0].cancel_penalty_group.description if room_stay.rate_plans and room_stay.rate_plans[0].cancel_penalty_group else "Политика отмены не детализирована."
        summary = f"{hotel_name_for_summary}: {room_type_display} по {rate_plan_display}. Итого: {price_display}. Политика: {cancellation_policy}"
        num_adults_in_offer, num_children_in_offer, _children_ages_list_offer = 0, 0, []
        if room_stay.guests:
            for g in room_stay.guests:
                is_child_flag = ("child" in (g.age_qualifying_code or "").lower()) or (g.age is not None and g.age_qualifying_code is None)
                if is_child_flag:
                    num_children_in_offer += g.count
                    if g.age is not None: _children_ages_list_offer.extend([str(g.age)] * g.count)
                else: num_adults_in_offer += g.count
        guest_summary_parts = []
        if num_adults_in_offer > 0: guest_summary_parts.append(f"{num_adults_in_offer} Взр.")
        if num_children_in_offer > 0:
            ages_str = ", ".join(sorted(list(set(_children_ages_list_offer)))) if _children_ages_list_offer else ""
            guest_summary_parts.append(f"{num_children_in_offer} Реб." + (f" (возр: {ages_str})" if ages_str else ""))
        final_guests_summary = ", ".join(guest_summary_parts) if guest_summary_parts else f"{actual_capacity_of_room_stay} Гостей (вместимость)"
        current_room_images = room_type_images_map.get(rt_code, [])
        details_dict = {
            "hotel_name": hotel_name_for_summary, "room_type_code": rt_code,
            "room_type_name": room_type_name_from_details, "room_images": current_room_images,
            "rate_plan_code": rp_code, "rate_plan_name": rate_plan_name_from_details,
            "applied_promo_info": applied_promo_info.strip(),
            "total_price": room_stay.total.price_after_tax, "currency": room_stay.total.currency,
            "cancellation_policy": cancellation_policy, "guests_summary": final_guests_summary,
            "num_adults_in_offer": num_adults_in_offer,
            "children_ages_in_offer": [int(age) for age in _children_ages_list_offer],
            "available_guarantees": [g.model_dump(exclude_none=True) for g in room_stay.guarantees] if room_stay.guarantees else []
        }
        options_results.append(BookingOptionResult(option_id=option_id, summary_text=summary, details=details_dict))

    logger.info(f"get_exely_booking_options - Возвращено {len(options_results)} вариантов бронирования после всех фильтраций.")
    if not options_results:
        if response.room_stays and promocode_or_rate_name_query :
             return [BookingOptionResult(option_id="no_suitable_options_promo", summary_text=f"В отеле '{hotel_name_for_summary}' по тарифу/промокоду '{promocode_or_rate_name_query}' нет подходящих номеров для вашего запроса, или они не соответствуют количеству гостей.", details={"reason": "promo_filter_no_match_capacity", "hotel_name": hotel_name_for_summary})]
        elif response.room_stays:
            return [BookingOptionResult(option_id="no_suitable_options", summary_text=f"В отеле '{hotel_name_for_summary}' найдены номера, но ни один точно не соответствует запрошенному количеству/типу гостей. Попробуйте изменить параметры поиска.", details={"reason": "capacity_mismatch", "hotel_name": hotel_name_for_summary})]
        else:
            no_rooms_msg = f"Для отеля '{hotel_name_for_summary}' на выбранные критерии ({params.check_in_date}-{params.check_out_date}, {params.num_adults} взр.) нет доступных номеров."
            reason_for_details = "no_availability"
            if response.warnings:
                hotel_not_found_warning = next((w.message for w in response.warnings if w.message and ("not found" in w.message.lower() or w.error_code == "392")), None)
                if hotel_not_found_warning: no_rooms_msg = f"Поиск не удался: {hotel_not_found_warning} (Отель: {hotel_code_to_search})"; reason_for_details = hotel_not_found_warning
                else:
                    first_warning_msg = response.warnings[0].message or f"API предупреждение (код: {response.warnings[0].error_code})"
                    no_rooms_msg = f"Для отеля '{hotel_name_for_summary}' нет доступных номеров. Примечание: {first_warning_msg}"; reason_for_details = first_warning_msg
            return [BookingOptionResult(option_id="no_options", summary_text=no_rooms_msg, details={"reason": reason_for_details, "hotel_name": hotel_name_for_summary})]
    return options_results

async def create_exely_reservation_and_get_link(params: CreateReservationToolParams) -> CreateReservationResult:
    # ... (код этой функции без изменений) ...
    logger.info(f"Выполнение инструмента Exely: 'create_exely_reservation_and_get_link' для booking_option_id: {params.booking_option_id}")
    if settings.DEBUG_MODE:
         logger.debug(f"Полные параметры для create_exely_reservation_and_get_link:\n{params.model_dump_json(indent=2, exclude_none=True)}")
    client = get_exely_client()
    selected_option_data: Optional[RoomStayAvailability] = BOOKING_OPTIONS_CACHE.get(params.booking_option_id)
    if not selected_option_data:
        logger.warning(f"Неверный или истекший booking_option_id: {params.booking_option_id}. Ключи кэша: {list(BOOKING_OPTIONS_CACHE.keys())}")
        return CreateReservationResult(booking_number="", status="error", cancellation_code="",error_message="Неверный или истекший ID варианта бронирования. Пожалуйста, выполните поиск заново.")

    total_guests_from_llm_params = len(params.guests)
    total_guest_capacity_from_cache = sum(gc.count for gc in selected_option_data.guests) if selected_option_data.guests else 0

    logger.info(f"Проверка количества гостей для бронирования: LLM предоставил {total_guests_from_llm_params} гостей. Вместимость кэшированного предложения для варианта {params.booking_option_id}: {total_guest_capacity_from_cache}.")

    if total_guests_from_llm_params != total_guest_capacity_from_cache:
        msg = (f"Несоответствие количества гостей для варианта бронирования {params.booking_option_id}. "
               f"Предложение (из кэша) ожидает {total_guest_capacity_from_cache} гостей, "
               f"но для бронирования было предоставлено {total_guests_from_llm_params}.")
        logger.error(msg)
        return CreateReservationResult(booking_number="", status="error", cancellation_code="", error_message=msg)

    reservation_rt_placements: List[RoomTypeReservationPlacement] = []
    original_placement_code_to_reservation_idx_map: Dict[str, int] = {}
    next_reservation_placement_index = 1
    if not selected_option_data.room_types or not selected_option_data.room_types[0].placements:
        msg = f"Критическая ошибка: кэшированные selected_option_data для {params.booking_option_id} не содержат room_types или placements."
        logger.error(msg); return CreateReservationResult(booking_number="",status="error",cancellation_code="",error_message=msg)
    for pp_avail in selected_option_data.room_types[0].placements:
        current_reservation_idx = next_reservation_placement_index
        reservation_rt_placements.append(RoomTypeReservationPlacement(index=current_reservation_idx, kind=pp_avail.kind, code=pp_avail.code))
        original_placement_code_to_reservation_idx_map[pp_avail.code] = current_reservation_idx
        next_reservation_placement_index += 1

    reservation_guest_counts_map: Dict[int, Dict[str, Any]] = {}
    if not selected_option_data.guests:
        msg = f"Критическая ошибка: кэшированные selected_option_data.guests для {params.booking_option_id} пусты."; logger.error(msg); return CreateReservationResult(booking_number="",status="error",cancellation_code="",error_message=msg)
    for gc_api_from_cache in selected_option_data.guests:
        target_pp_avail_for_gc = next((pp for pp in selected_option_data.room_types[0].placements if pp.index == gc_api_from_cache.placement.index), None)
        if not target_pp_avail_for_gc:
            msg = (f"Несоответствие данных: Не удалось сопоставить кэшированную группу гостей (исходный Exely placement.index {gc_api_from_cache.placement.index}) "
                   f"с оцененным размещением в cached offer's room_types[0].placements для варианта {params.booking_option_id}.")
            logger.error(msg)
            return CreateReservationResult(booking_number="", status="error", cancellation_code="", error_message=msg)
        reservation_idx_for_this_gc = original_placement_code_to_reservation_idx_map[target_pp_avail_for_gc.code]
        age_q_code = gc_api_from_cache.age_qualifying_code or ("child" if gc_api_from_cache.age is not None else "adult")
        if reservation_idx_for_this_gc not in reservation_guest_counts_map:
            reservation_guest_counts_map[reservation_idx_for_this_gc] = {"count": 0, "age_qualifying_code": age_q_code, "ages_list": []}
        current_map_entry = reservation_guest_counts_map[reservation_idx_for_this_gc]
        current_map_entry["count"] += gc_api_from_cache.count
        if gc_api_from_cache.age is not None: current_map_entry["ages_list"].extend([gc_api_from_cache.age] * gc_api_from_cache.count)
        if current_map_entry["age_qualifying_code"] != age_q_code and "child" not in current_map_entry["age_qualifying_code"].lower():
            current_map_entry["age_qualifying_code"] = age_q_code

    reservation_guest_counts_api: List[ExelyGuestCountDetailAPI] = []
    for res_idx, data_map_entry in reservation_guest_counts_map.items():
        age_to_send_api = None
        if "child" in data_map_entry["age_qualifying_code"].lower() and data_map_entry["ages_list"]:
            if len(set(data_map_entry["ages_list"])) == 1: age_to_send_api = data_map_entry["ages_list"][0]
            elif data_map_entry["ages_list"]:
                logger.warning(f"Несколько разных возрастов детей для placement_index {res_idx}: {data_map_entry['ages_list']}. Отправляется возраст первого ребенка ({data_map_entry['ages_list'][0]}).")
                age_to_send_api = data_map_entry['ages_list'][0]
        reservation_guest_counts_api.append(ExelyGuestCountDetailAPI(
            count=data_map_entry["count"], age_qualifying_code=data_map_entry["age_qualifying_code"],
            placement_index=res_idx, age=age_to_send_api ))

    reservation_guests_api_from_llm: List[ExelyGuestInfoAPI] = []
    guest_assignment_slots_indices_from_cache: List[int] = []
    for rtp_res_slot in reservation_rt_placements:
        num_guests_for_this_slot_type = next((rgc.count for rgc in reservation_guest_counts_api if rgc.placement_index == rtp_res_slot.index), 0)
        guest_assignment_slots_indices_from_cache.extend([rtp_res_slot.index] * num_guests_for_this_slot_type)

    if len(guest_assignment_slots_indices_from_cache) != total_guests_from_llm_params:
        msg = (f"Внутренняя ошибка при подготовке слотов для назначения гостей. Количество слотов из кэша ({len(guest_assignment_slots_indices_from_cache)}) "
               f"не совпадает с количеством гостей, предоставленных LLM ({total_guests_from_llm_params}) для варианта {params.booking_option_id}.")
        logger.error(msg)
        return CreateReservationResult(booking_number="", status="error", cancellation_code="", error_message=msg)

    for i, guest_llm_detail in enumerate(params.guests):
        reservation_guests_api_from_llm.append(ExelyGuestInfoAPI(
            first_name=guest_llm_detail.first_name, last_name=guest_llm_detail.last_name,
            middle_name=guest_llm_detail.middle_name, citizenship=guest_llm_detail.citizenship,
            placement=GuestPlacementRef(index=guest_assignment_slots_indices_from_cache[i]) ))
    if not selected_option_data.room_types or not selected_option_data.rate_plans:
        msg = f"Критическая ошибка (2): кэшированные selected_option_data для {params.booking_option_id} не содержат room_types или rate_plans."
        logger.error(msg); return CreateReservationResult(booking_number="",status="error",cancellation_code="",error_message=msg)

    room_stay_for_reservation = RoomStayReservation(
        stay_dates=selected_option_data.stay_dates,
        room_types=[RoomTypeReservation(code=selected_option_data.room_types[0].code,placements=reservation_rt_placements,preferences=[])],
        rate_plans=[RatePlanReservation(code=selected_option_data.rate_plans[0].code)],
        guest_count_info=ExelyGuestCountInfoAPI(guest_counts=reservation_guest_counts_api),
        guests=reservation_guests_api_from_llm, services=[])

    customer_api = ExelyCustomerReservationAPI(
        first_name=params.customer.first_name,last_name=params.customer.last_name,middle_name=params.customer.middle_name,
        comment=params.customer.comment or "",confirm_sms=False, subscribe_email=settings.DEFAULT_SUBSCRIBE_EMAIL,
        contact_info=ExelyCustomerContactInfoAPI(
            phones=[ExelyCustomerContactPhoneAPI(phone_number=params.customer.phone)],
            emails=[ExelyCustomerContactEmailAPI(email_address=params.customer.email)]))

    guarantee_api = ExelyGuaranteeReservationAPI(
        code=params.guarantee_code,success_url=str(settings.DEFAULT_SUCCESS_URL),decline_url=str(settings.DEFAULT_DECLINE_URL))

    hotel_reservation_item = HotelReservationRequestItem(
        hotel_ref=ExelyHotelRef(code=selected_option_data.hotel_ref.code),room_stays=[room_stay_for_reservation],
        guarantee=guarantee_api,customer=customer_api)

    reservation_language = params.language or settings.DEFAULT_LANGUAGE_LLM
    reservation_request_payload = HotelReservationRequest(
        language=reservation_language,hotel_reservations=[hotel_reservation_item],
        currency=selected_option_data.total.currency,
        point_of_sale=ExelyPointOfSaleAPI(source_url=str(settings.DEFAULT_POS_URL),integration_key=settings.DEFAULT_POS_INTEGRATION_KEY))

    try:
        response = await client.create_hotel_reservation(reservation_request_payload)
    except ExelyApiException as e:
        logger.error(f"API Exception в create_exely_reservation_and_get_link: {str(e)}", exc_info=settings.DEBUG_MODE)
        user_error_message = "Создание бронирования не удалось из-за проблемы с API. Детали записаны в лог."
        details_api_err_resp = None
        if isinstance(e.error_response, dict): details_api_err_resp = e.error_response.get("errors")
        if hasattr(e, 'status_code') and e.status_code == 400: # type: ignore
            user_error_message = "Создание бронирования не удалось: предоставлена неверная информация или несоответствие данных."
            if e.error_response and isinstance(e.error_response, dict) and e.error_response.get("errors"):
                api_errors = e.error_response.get("errors")
                if isinstance(api_errors, list) and api_errors and isinstance(api_errors[0], dict):
                    first_api_error_msg = api_errors[0].get("message")
                    if first_api_error_msg : user_error_message += f" (API: {first_api_error_msg})"
        return CreateReservationResult(booking_number="", status="error", cancellation_code="", error_message=user_error_message, details_api_errors=details_api_err_resp)
    finally:
        await client.close()

    if response.errors:
        logger.error(f"Создание бронирования вернуло ошибки в ответе: {response.errors}")
        first_error_obj = response.errors[0]
        error_msg = first_error_obj.message if first_error_obj and first_error_obj.message else "Неизвестная ошибка при бронировании."
        return CreateReservationResult(booking_number="", status="error", cancellation_code="", error_message=f"Бронирование не удалось: {error_msg}", details_api_errors=[err.model_dump() for err in response.errors] if settings.DEBUG_MODE else None)

    if not response.hotel_reservations:
        logger.error("Попытка создания бронирования не вернула массив 'hotel_reservations' и не вернула массив 'errors'. Это неожиданно.")
        return CreateReservationResult(booking_number="", status="error_unexpected_response", cancellation_code="", error_message="Попытка создания бронирования привела к неожиданному ответу от Exely.")

    reservation_details = response.hotel_reservations[0]
    payment_url_val = None
    if reservation_details.guarantee_info and reservation_details.guarantee_info.guarantees:
        first_guarantee_in_response = reservation_details.guarantee_info.guarantees[0]
        if first_guarantee_in_response.payment_url:
            payment_url_val = str(first_guarantee_in_response.payment_url)
    logger.info(f"Бронирование успешно создано. Номер брони: {reservation_details.number}, Статус: {reservation_details.status}, URL оплаты: {payment_url_val}")
    return CreateReservationResult(booking_number=reservation_details.number,status=reservation_details.status,cancellation_code=reservation_details.cancellation_code,payment_url=payment_url_val,order_url=str(reservation_details.order_url) if reservation_details.order_url else None)


async def cancel_exely_reservation(params: CancelReservationToolParams) -> CancelReservationResult:
    # ... (код этой функции без изменений) ...
    logger.info(f"Выполнение инструмента Exely: 'cancel_exely_reservation' для номера брони: {params.booking_number}")
    if settings.DEBUG_MODE:
        logger.debug(f"Параметры для cancel_exely_reservation:\n{params.model_dump_json(indent=2, exclude_none=True)}")
    client = get_exely_client()
    reasons_payload: Optional[List[CancelReservationReason]] = None
    if params.reason_code:
        reasons_payload = [CancelReservationReason(code=params.reason_code, text=params.reason_text)]
    cancel_payload = CancelReservationRequestPayload(
        hotel_reservation_refs=[
            CancelHotelReservationRef(
                number=params.booking_number,
                verification=CancelReservationVerification(cancellation_code=params.cancellation_code)
            )
        ],
        reasons=reasons_payload,
        language=params.language or settings.DEFAULT_LANGUAGE_LLM
    )
    try:
        response = await client.cancel_hotel_reservation(cancel_payload)
        if response.hotel_reservations and response.hotel_reservations[0].status.lower() == "cancelled":
            logger.info(f"Бронирование {params.booking_number} успешно отменено. Статус: {response.hotel_reservations[0].status}")
            return CancelReservationResult( booking_number=params.booking_number, status=response.hotel_reservations[0].status, message="Бронирование успешно отменено." )
        elif response.hotel_reservations:
            status_from_api = response.hotel_reservations[0].status
            logger.warning(f"Попытка отменить бронирование {params.booking_number} привела к статусу: {status_from_api}")
            return CancelReservationResult( booking_number=params.booking_number, status=status_from_api, message=f"Статус бронирования '{status_from_api}' после попытки отмены." )
        else: # Should not happen if API is consistent (either hotel_reservations or errors)
            logger.error(f"Попытка отмены для {params.booking_number} вернула неожиданную структуру ответа (нет hotel_reservations и нет ошибок в исходном ответе 200 OK).")
            return CancelReservationResult( booking_number=params.booking_number, status="error_unexpected_response", message="Попытка отмены привела к неожиданному ответу от API." )
    except ExelyApiException as e:
        logger.error(f"API Exception при cancel_exely_reservation для {params.booking_number}: {str(e)}", exc_info=settings.DEBUG_MODE)
        error_details_for_result = None
        if e.error_response and isinstance(e.error_response, dict): error_details_for_result = e.error_response.get("errors")
        return CancelReservationResult( booking_number=params.booking_number, status="error_api", message=f"Не удалось отменить бронирование: {str(e)}", error_details=error_details_for_result )
    except Exception as e_generic:
        logger.exception(f"Неожиданная ошибка при cancel_exely_reservation для {params.booking_number}", exc_info=True)
        return CancelReservationResult( booking_number=params.booking_number, status="error_internal", message=f"Произошла неожиданная внутренняя ошибка: {str(e_generic)}" )
    finally:
        await client.close()

async def process_natural_language_request(params: NlpRequestParams) -> Dict[str, Any]:
    logger.info(f"LLM Оркестратор получил запрос: '{params.raw_request}' от пользователя {params.user_id}, текущее действие бота: {params.current_bot_action}")

    if settings.DEBUG_MODE:
        raw_request_log = params.raw_request[:200] + '...' if len(params.raw_request) > 200 else params.raw_request
        history_log_parts = []
        if params.dialog_history:
            for turn in params.dialog_history[-5:]:
                history_log_parts.append(f"  - {turn.role}: {turn.content[:70] + '...' if len(turn.content) > 70 else turn.content}")
        history_log = "\n".join(history_log_parts) if history_log_parts else "  (пусто)"

        context_hotel_info_dict_for_log = params.context_hotel_info
        if hasattr(params.context_hotel_info, 'model_dump'):
            context_hotel_info_dict_for_log = params.context_hotel_info.model_dump(exclude_none=True) # type: ignore
        hotel_name_for_log = context_hotel_info_dict_for_log.get("name") if isinstance(context_hotel_info_dict_for_log, dict) else "N/A"

        context_customer_info_dict_for_log = params.context_customer_info
        if hasattr(params.context_customer_info, 'model_dump'):
            context_customer_info_dict_for_log = params.context_customer_info.model_dump(exclude_none=True) # type: ignore
        customer_email_for_log = context_customer_info_dict_for_log.get("email") if isinstance(context_customer_info_dict_for_log, dict) else "N/A"

        context_summary = {
            "hotel_info_name": hotel_name_for_log,
            "check_in": params.context_check_in_date, "check_out": params.context_check_out_date,
            "adults": params.context_num_adults, "children": params.context_children_ages,
            "selected_option_id": params.context_booking_option_id,
            "selected_guarantee_code": params.context_guarantee_code,
            "customer_email (context)": customer_email_for_log,
            "current_bot_action": params.current_bot_action
        }
        logger.debug(f"ОРКЕСТРАТОР ВХОД: Запрос='{raw_request_log}', История:\n{history_log}\nКонтекст: {json.dumps(context_summary, ensure_ascii=False)}")

    tools_description_str = get_tools_descriptions_for_llm()
    current_date_iso = datetime.now().strftime('%Y-%m-%d')
    current_time_iso = datetime.now().strftime('%H:%M:%S')
    current_year = datetime.now().year

    dialog_history_str_parts = []
    if params.dialog_history:
        for turn in params.dialog_history:
            dialog_history_str_parts.append(f"  - {turn.role}: {turn.content}")
    dialog_history_formatted = "\nPrevious conversation turns (most recent last):\n" + "\n".join(dialog_history_str_parts) if dialog_history_str_parts else "No previous conversation turns."

    context_hotel_info_dict = params.context_hotel_info
    if hasattr(context_hotel_info_dict, 'model_dump'):
        context_hotel_info_dict = context_hotel_info_dict.model_dump(exclude_none=True)

    hotel_name_from_context_for_prompt = f"отеля (код {settings.DEFAULT_HOTEL_CODE})"
    if context_hotel_info_dict and isinstance(context_hotel_info_dict, dict) and context_hotel_info_dict.get('name'):
        hotel_name_from_context_for_prompt = context_hotel_info_dict['name']

    context_parts = ["System Context (for your information, use it to avoid redundant questions):"]
    if context_hotel_info_dict and isinstance(context_hotel_info_dict, dict) and context_hotel_info_dict.get('name'):
        hotel_info_sub_parts = [f"  Current Hotel (code {context_hotel_info_dict.get('hotel_code', settings.DEFAULT_HOTEL_CODE)}):"]
        hotel_info_sub_parts.append(f"    Name: {hotel_name_from_context_for_prompt}")
        desc = context_hotel_info_dict.get('description')
        if desc: hotel_info_sub_parts.append(f"    Description (summary): {desc[:150] if desc else ''}...")
        services_summary = context_hotel_info_dict.get('services_summary')
        if services_summary: hotel_info_sub_parts.append(f"    Key Services: {', '.join(services_summary)}")
        context_parts.append("\n".join(hotel_info_sub_parts))
    else:
        context_parts.append(f"  Current Hotel: Information not yet retrieved. Default hotel_code: {settings.DEFAULT_HOTEL_CODE}.")

    search_ctx_parts = []
    if params.context_check_in_date: search_ctx_parts.append(f"check_in_date: {params.context_check_in_date}")
    if params.context_check_out_date: search_ctx_parts.append(f"check_out_date: {params.context_check_out_date}")
    if params.context_num_adults is not None: search_ctx_parts.append(f"num_adults: {params.context_num_adults}")
    if params.context_children_ages: search_ctx_parts.append(f"children_ages: {params.context_children_ages}")
    if search_ctx_parts: context_parts.append(f"  Current Search Parameters (use if user implies same criteria): {', '.join(search_ctx_parts)}.")
    else: context_parts.append("  Current Search Parameters: Not set.")

    if params.context_booking_option_id:
        context_parts.append(f"  Previously Selected Booking Option ID: {params.context_booking_option_id}")
    if params.context_guarantee_code:
        context_parts.append(f"  Previously Selected Guarantee Code: {params.context_guarantee_code}")

    context_customer_info_dict = params.context_customer_info
    if hasattr(context_customer_info_dict, 'model_dump'):
        context_customer_info_dict = context_customer_info_dict.model_dump(exclude_none=True)
    if context_customer_info_dict and isinstance(context_customer_info_dict, dict):
        customer_summary = ", ".join([f"{k}: {v}" for k, v in context_customer_info_dict.items()])
        context_parts.append(f"  Previously Provided Customer Info (for booking): {customer_summary}")

    context_bot_action_str = f"  Current Bot Action (what bot is waiting for): {params.current_bot_action or 'None (general query or start of new intent)'}."
    context_parts.append(context_bot_action_str)
    context_data_info_str = "\n".join(context_parts)

    example_response_json_structure = """
{
  "tool_name": "tool_to_call_or_null",
  "arguments": { "param1": "value1" /*, ... */ },
  "clarification_needed": "Your specific question to the user in Russian if information is missing or ambiguous for the CHOSEN tool, otherwise null. NEVER output instructions for yourself or placeholders like '{variable_name}' here. Avoid using ALL CAPS in clarifications."
}
""".strip()

    system_prompt_template = f"""
You are an expert hotel booking assistant for Exely. Your primary goal is to understand the user's Russian-language request, determine the correct tool, extract ALL necessary parameters, and if anything is missing FOR THE CHOSEN TOOL, ask a SINGLE, CLEAR clarification question in Russian. NEVER output instructions for yourself or placeholders like '{{variable_name}}' in 'clarification_needed'. Avoid using ALL CAPS in clarifications.

Current date: {current_date_iso}. Current time: {current_time_iso}. Current year: {current_year}.
If user says "на пару дней" or "на 2 дня", it means 2 nights. Calculate check_out_date based on check_in_date and number of nights.
Dates MUST be in YYYY-MM-DD format. Example: "14 июня" is "{current_year}-06-14". "15 число этого месяца" (if current month is June) is "{current_year}-06-15".

{dialog_history_formatted}
{context_data_info_str}

Available tools:
{tools_description_str}

Your response MUST be a single, valid JSON object with the following structure, and nothing else:
{example_response_json_structure}

Workflow and Tool Prioritization:

1.  **Initial Interaction / Hotel Info (`get_hotel_public_info`)**:
    *   If `current_bot_action` is 'start_command' AND `context_hotel_info` is "Information not yet retrieved", your ABSOLUTE FIRST action is `get_hotel_public_info`.
        *   Arguments: `hotel_code: "{settings.DEFAULT_HOTEL_CODE}"`, `language: "{settings.DEFAULT_LANGUAGE_LLM}"`.
        *   Set `clarification_needed: null`. (The bot will handle the greeting after this tool runs).
    *   If `context_hotel_info` IS ALREADY populated AND `current_bot_action` is 'start_command':
        `tool_name: null`, `clarification_needed: "Привет! Я ваш ассистент по отелю '{hotel_name_from_context_for_prompt}'. Чем могу помочь с информацией или бронированием?"`.
    *   If `context_hotel_info` IS ALREADY populated AND user's LATEST `raw_request` is a simple greeting/acknowledgement (e.g., "привет", "да", "спасибо", "хорошо") AND `current_bot_action` is NOT 'start_command':
        `tool_name: null`, `clarification_needed: "Привет! Я ваш ассистент по отелю '{hotel_name_from_context_for_prompt}'. Чем могу помочь с информацией или бронированием?"`.
    *   If `context_hotel_info` IS ALREADY populated AND user asks general questions (services, address etc.), provide a direct answer in `clarification_needed` based on 'description' or 'services_summary' from `context_hotel_info`.
        `tool_name: null`, `clarification_needed: "В отеле '{hotel_name_from_context_for_prompt}' есть [услуги из context_hotel_info.services_summary]. Адрес: [адрес из context_hotel_info.address]."`. DO NOT call `get_hotel_public_info` again if context for the current hotel is present.

2.  **Search Options (`get_exely_booking_options`)**:
    *   Call this if user wants to find rooms (e.g., "нужен номер", "поищи варианты", provides dates/guests) AND `context_hotel_info` is populated.
    *   **MANDATORY Parameters**: `check_in_date`, `check_out_date`, `num_adults`. `hotel_code` must be from `context_hotel_info.hotel_code` if available, else default.
    *   **Parameter Extraction**: Prioritize LATEST `raw_request`. Then `dialog_history`. Then `Current Search Parameters` from `System Context` (if user implies using same criteria).
    *   **Clarification for Search**: If ANY of `check_in_date`, `check_out_date`, OR `num_adults` are missing after checking all sources, set `tool_name: null` and ask for ALL missing ones in `clarification_needed`. Example: "Для поиска мне нужны: дата заезда, дата выезда (или количество ночей) и количество взрослых."
    *   Once all mandatory params are present, set `tool_name: "get_exely_booking_options"`, populate `arguments` (including `hotel_code`), `clarification_needed: null`.

3.  **User Chooses Booking Option (after `get_exely_booking_options` results were shown)**:
    *   If `current_bot_action` is 'awaiting_option_choice', the user's LATEST `raw_request` is likely their selection (e.g., "первый вариант", "бронируем A1").
    *   You MUST respond with `tool_name: null` and `clarification_needed: "Отлично! Для оформления бронирования, пожалуйста, укажите: имя и фамилию каждого гостя (латиницей). А также ваше полное имя (латиницей), email и номер телефона для связи."`. (Avoid ALL CAPS).
    *   The bot handles `booking_option_id` and `guarantee_code` internally. Do NOT try to extract these IDs yourself.

4.  **Collect Guest & Booker Details and Create Reservation (`create_exely_reservation_and_get_link`)**:
    *   Call this tool ONLY when:
        a. `Previously Selected Booking Option ID` AND `Previously Selected Guarantee Code` are present in `System Context`.
        b. `current_bot_action` is `awaiting_booking_details_llm`.
        c. User has provided ALL required `guests` details (list of `first_name`, `last_name` for EACH guest) AND ALL required `customer` details (main booker's `first_name`, `last_name`, `email`, `phone`) in their LATEST `raw_request` or very recent `dialog_history` (last 1-2 turns).
    *   **Parameter Extraction for Booking**:
        *   `guests`: Parse from LATEST `raw_request` or recent history. Ensure each guest has `first_name` and `last_name`.
        *   `customer`: Parse `first_name`, `last_name`, `email`, `phone` from LATEST `raw_request` or recent history. If `context_customer_info` exists and is complete, you can use it if user does not provide new details.
    *   **Clarification for Booking**:
        *   If `current_bot_action` is `awaiting_booking_details_llm` and any `guests` or `customer` details (first_name, last_name for guests; first_name, last_name, email, phone for customer) are still missing based on the user's LATEST input, set `tool_name: null` and ask ONLY for the SPECIFIC MISSING pieces. Example: "Спасибо. Теперь, пожалуйста, укажите email и телефон заказчика." or "Уточните, пожалуйста, имя и фамилию для второго гостя." (Avoid ALL CAPS).
        *   If user provides names like "John Doe, Jane Doe", parse them as two guests.
    *   If all data is present and valid, set `tool_name: "create_exely_reservation_and_get_link"`, populate ALL `arguments` (including `guests`, and `customer`). `booking_option_id` and `guarantee_code` will be injected by the system from context. Set `clarification_needed: null`.

5.  **Cancel Reservation (`cancel_exely_reservation`)**:
    *   If user wants to cancel and provides `booking_number` and `cancellation_code` in their LATEST `raw_request`, call this tool.
    *   If user expresses intent to cancel but details are missing, ask for them: `tool_name: null`, `clarification_needed: "Для отмены бронирования, пожалуйста, укажите номер бронирования и код отмены."`.

General Rules:
- Default hotel code: {settings.DEFAULT_HOTEL_CODE}. Default language for clarifications: ru.
- If information for the INTENDED tool is missing (and not covered by specific clarification rules above), ALWAYS set `tool_name: null` and provide a FOCUSED `clarification_needed` question in Russian. Avoid ALL CAPS.
- Only ask for ONE logical set of information at a time (e.g., all missing search params, or all guest names, or all booker contacts).
- If `current_bot_action` indicates specific information is awaited (e.g., 'awaiting_clarification', 'awaiting_booking_details_llm'), prioritize parsing the LATEST `raw_request` to fulfill those needs.
- Your JSON output must be perfect. No extra text. Do not explain your reasoning in the JSON.
"""
    if settings.DEBUG_MODE:
        logger.debug(f"Системный промпт для LLM оркестратора (длина: {len(system_prompt_template)}):\n{system_prompt_template}")
    else:
        logger.debug(f"Системный промпт для LLM оркестратора (длина: {len(system_prompt_template)}): Первые 500 символов: {system_prompt_template[:500]}...")

    llm_structured_response = await get_llm_response(system_prompt_template, params.raw_request)

    if not llm_structured_response:
        logger.error("LLM get_llm_response вернул None, это неожиданно.")
        return {"tool_name": None, "arguments": {}, "clarification_needed": "Произошла внутренняя ошибка. Пожалуйста, попробуйте позже."}

    if isinstance(llm_structured_response, dict) and "_llm_rate_limit_exceeded_" in llm_structured_response:
        return llm_structured_response

    if isinstance(llm_structured_response, dict) and ("error" in llm_structured_response or "_mcp_client_error_" in llm_structured_response) :
        error_msg = "LLM не ответил или произошла ошибка."
        if isinstance(llm_structured_response, dict):
            error_msg = llm_structured_response.get("message") or llm_structured_response.get("error", error_msg)
        logger.error(f"Ошибка от LLM или клиента в оркестраторе: {error_msg}")
        # Pass the potentially more user-friendly message if it was set by call_mcp_tool_orchestrator for rate limit
        return {"_mcp_client_error_": True, "message": error_msg, "details": llm_structured_response.get("details", error_msg)}


    logger.info(f"Ответ LLM оркестратора: {llm_structured_response}")

    if not isinstance(llm_structured_response, dict) or \
       not ("tool_name" in llm_structured_response and \
            "arguments" in llm_structured_response and \
            "clarification_needed" in llm_structured_response):
        logger.error(f"Ответ LLM не соответствует ожидаемой структуре: {llm_structured_response}")
        error_detail_for_user = ""
        if settings.DEBUG_MODE and llm_structured_response and isinstance(llm_structured_response, dict):
            try: error_detail_for_user = f" (Детали: {json.dumps(llm_structured_response, ensure_ascii=False, indent=2)})"
            except TypeError: error_detail_for_user = " (Не удалось сериализовать детали ответа LLM)"
        elif settings.DEBUG_MODE and llm_structured_response:
            error_detail_for_user = f" (Ответ LLM: {str(llm_structured_response)[:200]})"
        return {"tool_name": None, "arguments": {}, "clarification_needed": f"Я получил неожиданный ответ от языковой модели и не могу продолжить.{error_detail_for_user} Попробуйте переформулировать запрос."}

    tool_name_chosen = llm_structured_response.get("tool_name")
    arguments_chosen = llm_structured_response.get("arguments", {})

    if tool_name_chosen == "create_exely_reservation_and_get_link":
        if "booking_option_id" in arguments_chosen:
            logger.warning(f"LLM попытался предоставить 'booking_option_id' ({arguments_chosen['booking_option_id']}) для create_exely_reservation_and_get_link. Он должен браться из контекста. Удаляю.")
            del arguments_chosen["booking_option_id"]
        if "guarantee_code" in arguments_chosen:
            logger.warning(f"LLM попытался предоставить 'guarantee_code' ({arguments_chosen['guarantee_code']}) для create_exely_reservation_and_get_link. Он должен браться из контекста. Удаляю.")
            del arguments_chosen["guarantee_code"]
        llm_structured_response["arguments"] = arguments_chosen


    if tool_name_chosen and not arguments_chosen:
        if tool_name_chosen in ["get_exely_booking_options", "create_exely_reservation_and_get_link", "cancel_exely_reservation"] or \
           (tool_name_chosen == "get_hotel_public_info" and not arguments_chosen.get("hotel_code")):
            logger.warning(f"LLM выбрал инструмент '{tool_name_chosen}', но не предоставил аргументы (или не hotel_code для get_hotel_public_info). Запрашиваю уточнение.")
            llm_structured_response["clarification_needed"] = "Кажется, я не получил все необходимые детали для этого действия. Не могли бы вы уточнить ваш запрос?"
            llm_structured_response["tool_name"] = None

    if llm_structured_response.get("tool_name") is None and not llm_structured_response.get("clarification_needed"):
        logger.warning("LLM указал на необходимость уточнения (tool_name is None), но не предоставил текст. Использую стандартный запрос.")
        llm_structured_response["clarification_needed"] = "Не могли бы вы уточнить ваш запрос? Мне не совсем понятны некоторые детали."

    return llm_structured_response
