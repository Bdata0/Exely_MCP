import httpx
from typing import Optional, Dict, Any, List, Tuple
import logging
import json

# Убедимся, что импортируем все необходимые схемы
from .schemas import (
    HotelAvailabilityRequestParams, HotelAvailabilityResponse,
    HotelReservationRequest, HotelReservationResponse,
    CancelReservationRequestPayload, CancelReservationResponsePayload,
    ErrorDetail,
    # Добавим схему для параметров запроса hotel_info, если она будет простой
    # или определим ее прямо здесь, если она специфична только для этого клиента
)
from app.config import settings

logger = logging.getLogger(__name__)

class ExelyApiException(Exception):
    """Custom exception for Exely API errors."""
    def __init__(self, status_code: Optional[int] = None, error_response: Optional[Dict[str, Any]] = None, message: Optional[str] = None, request_url: Optional[str] = None):
        self.status_code = status_code
        self.error_response = error_response
        self.request_url = request_url
        super().__init__(message or "Exely API request failed")


def _flatten_availability_params(params: HotelAvailabilityRequestParams) -> List[Tuple[str, str]]:
    flat_params: List[Tuple[str, Any]] = []

    if params.language is not None:
        flat_params.append(("language", params.language))
    if params.currency is not None:
        flat_params.append(("currency", params.currency))
    if params.include_rates is not None:
        flat_params.append(("include_rates", params.include_rates))
    if params.include_transfers is not None:
        flat_params.append(("include_transfers", params.include_transfers))
    if params.include_all_placements is not None:
        flat_params.append(("include_all_placements", params.include_all_placements))
    if params.include_promo_restricted is not None:
        flat_params.append(("include_promo_restricted", params.include_promo_restricted))

    for i, criterion in enumerate(params.criterions):
        flat_params.append((f"criterions[{i}].ref", criterion.ref or "0"))
        for j, hotel_ref in enumerate(criterion.hotels):
            flat_params.append((f"criterions[{i}].hotels[{j}].code", hotel_ref.code))
        flat_params.append((f"criterions[{i}].dates", criterion.dates))
        flat_params.append((f"criterions[{i}].adults", criterion.adults))
        if criterion.children is not None:
            flat_params.append((f"criterions[{i}].children", criterion.children))

    final_params: List[Tuple[str, str]] = []
    for k, v in flat_params:
        if isinstance(v, bool):
            final_params.append((k, str(v).lower()))
        else:
            final_params.append((k, str(v)))
    return final_params

class ExelyDistributionApiClient:
    def __init__(self, api_key: str, base_url: str = "https://ibe.hopenapi.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.headers = {
            "X-ApiKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        client_timeout = getattr(settings, 'EXELY_CLIENT_TIMEOUT', 30.0)
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=client_timeout)
        logger.debug(f"ExelyDistributionApiClient initialized for base_url: {self.base_url}, timeout: {client_timeout}s")
        if self.api_key == "YOUR_EXELY_API_KEY_PLACEHOLDER" or not self.api_key:
             logger.critical("EXELY_API_KEY is a placeholder or empty! API calls will likely fail.")


    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[List[Tuple[str, str]]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        log_url = httpx.URL(self.base_url + endpoint)
        if params:
            log_url = log_url.copy_with(params=params)

        request_details_for_log = [
            f"Exely API Request:",
            f"  Method: {method}",
            f"  URL: {log_url}",
        ]

        if json_data and settings.DEBUG_MODE:
            try:
                request_details_for_log.append(f"  Body (prepared for httpx):\n{json.dumps(json_data, indent=2, ensure_ascii=False)}")
            except TypeError as te:
                 request_details_for_log.append(f"  Body: (Could not serialize to JSON for logging: {te})")
                 logger.error(f"Error serializing json_data for logging (request to {log_url}): {te}", exc_info=True)
        logger.debug("\n".join(request_details_for_log))

        try:
            response = await self._client.request(method, endpoint, params=params, json=json_data)

            response_body_text = response.text
            response_body_json_parsed: Optional[Dict[str, Any]] = None
            try:
                response_body_json_parsed = json.loads(response_body_text)
            except json.JSONDecodeError:
                logger.warning(f"Response body for {method} {endpoint} is not valid JSON.")

            log_response_parts = [
                f"Exely API Response:",
                f"  Status Code: {response.status_code}",
                f"  URL: {response.url}"
            ]
            if settings.DEBUG_MODE:
                log_response_parts.append(f"  Headers:")
                for k, v_resp in response.headers.items():
                    log_response_parts.append(f"    {k}: {v_resp}")
                log_response_parts.append(f"  Body:")
                if response_body_json_parsed:
                    log_response_parts.append(json.dumps(response_body_json_parsed, indent=2, ensure_ascii=False))
                else:
                    log_response_parts.append(response_body_text if len(response_body_text) < 2000 else response_body_text[:2000] + "...")

            logger.debug("\n".join(log_response_parts))

            response.raise_for_status()

            if response_body_json_parsed is None:
                err_msg = f"API request to {response.url} received status {response.status_code} but response was not valid JSON."
                logger.error(err_msg)
                raise ExelyApiException(
                    status_code=response.status_code,
                    message=err_msg,
                    request_url=str(response.url)
                )
            return response_body_json_parsed

        except httpx.HTTPStatusError as e:
            error_response_parsed: Optional[Dict[str, Any]] = None
            try:
                error_response_parsed = e.response.json()
            except json.JSONDecodeError:
                pass

            msg_for_exception = (
                f"API request to {e.request.url} failed with status {e.response.status_code}. "
                f"Response: {json.dumps(error_response_parsed, indent=2, ensure_ascii=False) if error_response_parsed else e.response.text}"
            )
            logger.error(f"HTTPStatusError during Exely API call: {msg_for_exception}", exc_info=settings.DEBUG_MODE)
            raise ExelyApiException(
                status_code=e.response.status_code,
                error_response=error_response_parsed or {"raw_error_text": e.response.text},
                message=msg_for_exception,
                request_url=str(e.request.url)
            ) from e
        except httpx.RequestError as e:
            msg = f"Network request failed for {e.request.url}: {str(e)}"
            logger.error(msg, exc_info=settings.DEBUG_MODE)
            raise ExelyApiException(message=msg, request_url=str(e.request.url)) from e
        except TypeError as te:
            msg = f"TypeError during request preparation for {log_url}: {str(te)}. This often means a non-serializable type was passed."
            logger.error(msg, exc_info=True)
            raise ExelyApiException(message=msg, request_url=str(log_url)) from te
        except Exception as e:
            msg = f"An unexpected error occurred during API request to {log_url}: {str(e)}"
            logger.exception(msg)
            raise ExelyApiException(message=msg, request_url=str(log_url)) from e

    async def get_hotel_info(
        self, hotel_code: str, language: str = settings.DEFAULT_LANGUAGE
    ) -> Dict[str, Any]: # TODO: Заменить Dict[str, Any] на Pydantic модель HotelInfoResponse, когда она будет определена
        """
        Получает подробную информацию об отеле.
        """
        logger.info(f"Запрос информации об отеле: код={hotel_code}, язык={language}")

        query_params: List[Tuple[str, str]] = [
            ("language", language),
            ("hotels[0].code", hotel_code) # Exely API ожидает параметры в таком формате для массивов
        ]

        api_response_dict = await self._request(
            method="GET",
            endpoint="/ChannelDistributionApi/BookingForm/hotel_info",
            params=query_params,
        )

        # TODO: Добавить валидацию с помощью Pydantic модели, когда HotelInfoResponse будет готова.
        # try:
        #     validated_response = HotelInfoResponse.model_validate(api_response_dict)
        #     logger.info(f"Информация об отеле {hotel_code} успешно получена и валидирована.")
        #     return validated_response
        # except Exception as e_val:
        #     msg = f"Не удалось валидировать HotelInfoResponse для отеля {hotel_code}: {str(e_val)}"
        #     response_summary_for_log = json.dumps(api_response_dict, indent=2, ensure_ascii=False)
        #     if len(response_summary_for_log) > 2000 and not settings.DEBUG_MODE:
        #          response_summary_for_log = response_summary_for_log[:2000] + "..."
        #     logger.error(f"{msg}\nRaw API response for validation was:\n{response_summary_for_log}", exc_info=settings.DEBUG_MODE)
        #     raise ExelyApiException(message=msg, error_response=api_response_dict, status_code=200) from e_val

        # Пока что возвращаем сырой словарь
        if api_response_dict.get("errors"):
            logger.warning(f"API вернул ошибки при запросе hotel_info для {hotel_code}: {api_response_dict['errors']}")
            # Можно бросить исключение или вернуть словарь с ошибками
            # raise ExelyApiException(status_code=400, error_response=api_response_dict, message=f"API errors for hotel_info {hotel_code}")

        logger.info(f"Информация об отеле {hotel_code} успешно получена.")
        return api_response_dict


    async def get_hotel_availability(
        self, request_data: HotelAvailabilityRequestParams
    ) -> HotelAvailabilityResponse:
        criterions_summary = "N/A"
        if request_data.criterions:
            first_crit = request_data.criterions[0]
            hotel_codes = [h.code for h in first_crit.hotels]
            criterions_summary = f"hotels: {hotel_codes}, dates: {first_crit.dates}, adults: {first_crit.adults}"
        logger.info(f"Запрос доступности отеля ({criterions_summary})")

        if not request_data.criterions:
            logger.error("Список критериев не может быть пустым для поиска hotel_availability.")
            raise ValueError("Список критериев не может быть пустым для поиска hotel_availability.")

        query_params: List[Tuple[str, str]] = _flatten_availability_params(request_data)

        api_response_dict = await self._request(
            method="GET",
            endpoint="/ChannelDistributionApi/BookingForm/hotel_availability",
            params=query_params,
        )
        try:
            validated_response = HotelAvailabilityResponse.model_validate(api_response_dict)
            logger.info(f"Ответ о доступности отеля валидирован. Найдено {len(validated_response.room_stays)} вариантов комнат.")
            return validated_response
        except Exception as e_val:
            msg = f"Не удалось валидировать HotelAvailabilityResponse: {str(e_val)}"
            response_summary_for_log = json.dumps(api_response_dict, indent=2, ensure_ascii=False)
            if len(response_summary_for_log) > 2000 and not settings.DEBUG_MODE:
                 response_summary_for_log = response_summary_for_log[:2000] + "..."
            logger.error(f"{msg}\nRaw API response for validation was:\n{response_summary_for_log}", exc_info=settings.DEBUG_MODE)
            raise ExelyApiException(message=msg, error_response=api_response_dict, status_code=200) from e_val


    async def create_hotel_reservation(
        self, reservation_request_data: HotelReservationRequest
    ) -> HotelReservationResponse:
        hotel_code = "N/A"
        if reservation_request_data.hotel_reservations:
            hotel_code = reservation_request_data.hotel_reservations[0].hotel_ref.code
        logger.info(f"Создание бронирования для отеля: {hotel_code}")

        json_payload = reservation_request_data.model_dump(mode='json', by_alias=True, exclude_none=True)
        if settings.DEBUG_MODE:
            logger.debug(f"Полезная нагрузка для бронирования (JSON):\n{json.dumps(json_payload, indent=2, ensure_ascii=False)}")

        api_response_dict = await self._request(
            method="POST",
            endpoint="/ChannelDistributionApi/BookingForm/hotel_reservation_2",
            json_data=json_payload,
        )

        if isinstance(api_response_dict.get("errors"), list) and api_response_dict["errors"]:
            first_error = api_response_dict["errors"][0]
            error_message_from_api = first_error.get("message", "Неизвестная ошибка из массива ошибок API.")
            error_code_from_api = first_error.get("error_code", "N/A")

            full_error_message_for_exception = (
                f"API запрос к {self.base_url}/ChannelDistributionApi/BookingForm/hotel_reservation_2 "
                f"получил 200 OK, но ответ содержит ошибки уровня приложения. "
                f"Первая ошибка (код: {error_code_from_api}): {error_message_from_api}"
            )
            logger.warning(f"create_hotel_reservation: {full_error_message_for_exception}. Полные ошибки от API: {json.dumps(api_response_dict['errors'], indent=2, ensure_ascii=False)}")
            raise ExelyApiException(
                status_code=400,
                error_response=api_response_dict,
                message=full_error_message_for_exception,
                request_url=self.base_url + "/ChannelDistributionApi/BookingForm/hotel_reservation_2"
            )

        try:
            validated_response = HotelReservationResponse.model_validate(api_response_dict)
            if validated_response.hotel_reservations and validated_response.hotel_reservations[0].number:
                 logger.info(f"Ответ о бронировании отеля валидирован. Номер брони: {validated_response.hotel_reservations[0].number}, Статус: {validated_response.hotel_reservations[0].status}")
            else:
                 logger.warning("Ответ о бронировании отеля валидирован, но номер брони не найден или отсутствуют другие ожидаемые данные (и нет массива 'errors' в ответе).")
            return validated_response
        except Exception as e_val:
            msg = f"Не удалось валидировать HotelReservationResponse (ожидалась успешная структура): {str(e_val)}"
            response_summary_for_log = json.dumps(api_response_dict, indent=2, ensure_ascii=False)
            if len(response_summary_for_log) > 2000 and not settings.DEBUG_MODE:
                 response_summary_for_log = response_summary_for_log[:2000] + "..."
            logger.error(f"{msg}\nRaw API response for validation was:\n{response_summary_for_log}", exc_info=settings.DEBUG_MODE)
            raise ExelyApiException(message=msg, error_response=api_response_dict, status_code=200) from e_val


    async def cancel_hotel_reservation(
        self, cancel_request_data: CancelReservationRequestPayload
    ) -> CancelReservationResponsePayload:
        booking_number_to_cancel = "N/A"
        if cancel_request_data.hotel_reservation_refs:
            booking_number_to_cancel = cancel_request_data.hotel_reservation_refs[0].number
        logger.info(f"Попытка отменить бронирование отеля: {booking_number_to_cancel}")

        json_payload = cancel_request_data.model_dump(mode='json', by_alias=True, exclude_none=True)
        if settings.DEBUG_MODE:
            logger.debug(f"Полезная нагрузка для отмены бронирования (JSON):\n{json.dumps(json_payload, indent=2, ensure_ascii=False)}")

        api_response_dict = await self._request(
            method="POST",
            endpoint="/ChannelDistributionApi/BookingForm/cancel_reservation_2",
            json_data=json_payload,
        )

        if isinstance(api_response_dict.get("errors"), list) and api_response_dict["errors"]:
            first_error = api_response_dict["errors"][0]
            error_message_from_api = first_error.get("message", "Неизвестная ошибка из массива ошибок API при отмене.")
            error_code_from_api = first_error.get("error_code", "N/A")
            full_error_message_for_exception = (
                f"API запрос на отмену бронирования {booking_number_to_cancel} "
                f"получил 200 OK, но ответ содержит ошибки уровня приложения. "
                f"Первая ошибка (код: {error_code_from_api}): {error_message_from_api}"
            )
            logger.warning(f"cancel_hotel_reservation: {full_error_message_for_exception}. Полные ошибки от API: {json.dumps(api_response_dict['errors'], indent=2, ensure_ascii=False)}")
            raise ExelyApiException(
                status_code=400,
                error_response=api_response_dict,
                message=full_error_message_for_exception,
                request_url=self.base_url + "/ChannelDistributionApi/BookingForm/cancel_reservation_2"
            )

        try:
            validated_response = CancelReservationResponsePayload.model_validate(api_response_dict)
            if validated_response.hotel_reservations:
                logger.info(f"Ответ об отмене бронирования валидирован для {validated_response.hotel_reservations[0].number}. Статус: {validated_response.hotel_reservations[0].status}")
            else:
                logger.warning("Ответ об отмене бронирования валидирован, но нет массива hotel_reservations (и нет массива 'errors').")
            return validated_response
        except Exception as e_val:
            msg = f"Не удалось валидировать CancelReservationResponsePayload: {str(e_val)}"
            response_summary_for_log = json.dumps(api_response_dict, indent=2, ensure_ascii=False)
            if len(response_summary_for_log) > 2000 and not settings.DEBUG_MODE:
                 response_summary_for_log = response_summary_for_log[:2000] + "..."
            logger.error(f"{msg}\nRaw API response for validation was:\n{response_summary_for_log}", exc_info=settings.DEBUG_MODE)
            raise ExelyApiException(message=msg, error_response=api_response_dict, status_code=200) from e_val


    async def close(self):
        await self._client.aclose()
        logger.debug("ExelyDistributionApiClient HTTP клиент закрыт.")
