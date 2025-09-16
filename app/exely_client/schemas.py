# app/exely_client/schemas.py

from typing import List, Optional, Union, Dict, Any, Literal
from pydantic import BaseModel, Field, AnyHttpUrl, conint, constr # Убрал неиспользуемый date
from datetime import datetime

# --- Вспомогательные модели (Auxiliary Models) ---

class HotelRef(BaseModel):
    code: str = Field(..., description="Hotel ID.")
    name: Optional[str] = Field(None, description="Hotel name (present in reservation response).")
    stay_unit_kind: Optional[str] = Field(None, description="Room price calculation unit (e.g., 'night') (present in reservation response).")

class TaxItem(BaseModel):
    amount: float = Field(..., description="Amount of tax or fee.")
    code: str = Field(..., description="Tax or fee ID.")

class DiscountInfo(BaseModel):
    basic_before_tax: float = Field(..., description="Original price before tax before discount.")
    basic_after_tax: float = Field(..., description="Original price after tax before discount.")
    amount: float = Field(..., description="Total discount amount.")
    currency: Optional[constr(min_length=3, max_length=3)] = Field(None, description="Currency of the discount amount, if different from main.")

class PriceInfo(BaseModel):
    price_before_tax: float = Field(..., description="Price before taxes.")
    price_after_tax: float = Field(..., description="Price after taxes, including all applicable taxes.")
    currency: constr(min_length=3, max_length=3) = Field(..., description="ISO 4217 currency code (e.g., 'USD', 'EUR').")
    taxes: List[TaxItem] = Field(default_factory=list, description="Taxes and fees included in this price.")
    discount: Optional[DiscountInfo] = Field(None, description="Discount details if applicable.")

class GuaranteeInfo(BaseModel): # Используется в hotel_availability response
    code: str = Field(..., description="Unique code for the guarantee/payment method.")
    primary_guarantee_code: Optional[str] = Field(None, description="Primary guarantee code if applicable.")
    type: str = Field(..., description="Payment method type (e.g., 'cash', 'guarantee').")
    payment_system_code: Optional[str] = Field(None, description="Specific payment system code (e.g., 'AT_ARRIVAL').")
    name: Optional[str] = Field(None, description="Human-readable name of the guarantee method.") # Добавлено, может быть в hotel_info
    payment_url: Optional[AnyHttpUrl] = Field(None, description="URL for online payment, if applicable.")


class DateRangeStay(BaseModel):
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", description="Arrival date and time in 'YYYY-MM-DD HH:MM:SS' format.")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", description="Departure date and time in 'YYYY-MM-DD HH:MM:SS' format.")

# --- hotel_availability REQUEST Models ---

class HotelAvailabilityCriterionHotel(BaseModel):
    code: str = Field(..., description="Hotel ID.")

class HotelAvailabilityCriterion(BaseModel):
    ref: Optional[str] = Field("0", description="ID for request-response reference.")
    hotels: List[HotelAvailabilityCriterionHotel] = Field(..., min_length=1, description="List of hotels to search.")
    dates: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2};\d{4}-\d{2}-\d{2}$", description="Stay dates as 'YYYY-MM-DD;YYYY-MM-DD'.")
    adults: conint(ge=0) = Field(..., description="Number of adult guests.")
    children: Optional[str] = Field(None, pattern=r"^(\d{1,2}(,\d{1,2})*)?$", description="Comma-separated ages (e.g., '5,10').")

class HotelAvailabilityRequestParams(BaseModel):
    include_transfers: bool = Field(..., description="Include transfers in response.")
    language: str = Field(..., description="Language of the response.")
    criterions: List[HotelAvailabilityCriterion] = Field(..., min_length=1, description="Request criteria.")
    include_rates: Optional[bool] = Field(True, description="Include rate plan details.")
    include_all_placements: Optional[bool] = Field(True, description="Include all guest placements.")
    include_promo_restricted: Optional[bool] = Field(True, description="Include promo-restricted rates.")
    currency: Optional[constr(min_length=3, max_length=3)] = Field("USD", description="Preferred currency.")

# --- hotel_availability RESPONSE Models ---

class PlacementPrice(BaseModel):
    index: int = Field(..., description="Accommodation index.")
    price_before_tax: float
    price_after_tax: float
    kind: str = Field(..., description="Type of accommodation (e.g., 'adult').")
    code: str = Field(..., description="Accommodation ID.")
    capacity: int
    currency: constr(min_length=3, max_length=3)
    taxes: List[TaxItem] = Field(default_factory=list)
    discount: Optional[DiscountInfo] = None
    age_group: Optional[Union[int,str]] = Field(None, description="Age group code for child placements.")

class RoomTypeAvailabilityInfo(BaseModel):
    placements: List[PlacementPrice] = Field(..., description="Accommodation pricing.")
    code: str = Field(..., description="Room category ID.")
    quantity: Optional[int] = Field(None, ge=0)
    limited_inventory_count: Optional[int] = None
    room_type_quota_rph: Optional[str] = None

class RatePlanCancelPenalty(BaseModel):
    code: str
    description: str
    # Дополнения из примера hotel_info для cancel_penalty_group.cancel_penalties
    deadline: Optional[Dict[str, Any]] = None # Пример: {"offset_drop_time": "before_policy_check_in_time"}
    time_match: Optional[Dict[str, Any]] = None # Пример: {"time_unit": "hour", "matching": "any"}
    guests_count_match: Optional[Dict[str, Any]] = None
    rooms_count_match: Optional[Dict[str, Any]] = None
    periods: Optional[List[Dict[str, Any]]] = None # Пример: [{"start_date": "2018-11-09"}]
    penalty: Optional[Dict[str, Any]] = None # Пример: {"nights": 1, "type": "relative_to_basis", "basis": "nights"}


class RatePlanCancelPenaltyGroupInAvailability(BaseModel): # Используется в hotel_availability
    code: str
    description: str
    free_cancellation: Optional[bool] = None
    show_description: bool
    cancel_penalties: List[RatePlanCancelPenalty] = Field(default_factory=list)

class RatePlanAvailabilityInfo(BaseModel): # Используется в hotel_availability
    code: str
    cancel_penalty_group: RatePlanCancelPenaltyGroupInAvailability
    promo: bool = False

class GuestPlacementRef(BaseModel):
    index: int

class GuestPlacementInPlacementRates(BaseModel):
    index: int
    kind: str
    code: str

class DailyRate(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    price_after_tax: float
    currency: constr(min_length=3, max_length=3)
    taxes: List[TaxItem] = Field(default_factory=list)

class PlacementRateInfo(BaseModel):
    room_type_code: str
    rate_plan_code: str
    placement: GuestPlacementInPlacementRates
    rates: List[DailyRate]

class GuestCount(BaseModel):
    placement: GuestPlacementRef
    count: int = Field(..., ge=0)
    age: Optional[int] = Field(None, ge=0)
    age_qualifying_code: Optional[str] = Field(None)
    ref: Optional[str] = None

class ServiceInRoomStay(BaseModel):
    rph: int
    applicability_type: Optional[str] = None

class RoomStayAvailability(BaseModel): # Результат для hotel_availability
    hotel_ref: HotelRef
    guests: List[GuestCount]
    room_types: List[RoomTypeAvailabilityInfo]
    rate_plans: List[RatePlanAvailabilityInfo]
    placement_rates: List[PlacementRateInfo]
    criterion_ref: str
    total: PriceInfo
    services: List[ServiceInRoomStay] = Field(default_factory=list)
    stay_dates: DateRangeStay
    guarantees: List[GuaranteeInfo]
    transfers: List[dict] = Field(default_factory=list)

class ServiceDetailInAvailability(BaseModel):
    code: str
    rph: int
    price: PriceInfo
    inclusive: bool
    quantity: Optional[int] = Field(None, ge=0)
    applicability_type: Optional[str] = None

class VehicleInTransfer(BaseModel):
    vehicle_code: str
    price_before_tax: float
    price_after_tax: float
    currency: constr(min_length=3, max_length=3)
    taxes: List[TaxItem] = Field(default_factory=list)

class TransferDetailInAvailability(BaseModel):
    rph: int
    transfer_code: str
    vehicles: List[VehicleInTransfer]

class RoomTypeQuota(BaseModel):
    rph: str
    quantity: int = Field(..., ge=0)

class AvailabilityResultMessage(BaseModel):
    criterion_ref: Optional[str] = None
    no_room_type_availability_message: Optional[str] = None

class ErrorDetail(BaseModel):
    error_code: str
    message: str
    lang: Optional[str] = None
    info: Optional[str] = None
    location: Optional[str] = None

class WarningDetail(BaseModel):
    error_code: str
    message: str
    lang: Optional[str] = None
    info: Optional[str] = None
    location: Optional[str] = None

class HotelAvailabilityResponse(BaseModel):
    room_stays: List[RoomStayAvailability] = Field(default_factory=list)
    transfers: List[TransferDetailInAvailability] = Field(default_factory=list)
    services: List[ServiceDetailInAvailability] = Field(default_factory=list)
    availability_result: List[AvailabilityResultMessage] = Field(default_factory=list)
    room_type_quotas: List[RoomTypeQuota] = Field(default_factory=list)
    errors: Optional[List[ErrorDetail]] = None
    warnings: Optional[List[WarningDetail]] = None

# --- hotel_reservation_2 REQUEST Models ---
# (Существующие модели для hotel_reservation_2 остаются без изменений)
# ... (все модели от RoomTypeReservationPlacement до HotelReservationRequest)

class RoomTypeReservationPlacement(BaseModel):
    index: int
    kind: str
    code: str

class RoomTypeReservation(BaseModel):
    code: str
    placements: List[RoomTypeReservationPlacement] = Field(..., min_length=1)
    preferences: List[dict] = Field(default_factory=list)

class RatePlanReservation(BaseModel):
    code: str

class GuestCountDetailAPI(BaseModel):
    count: int = Field(..., ge=1)
    age_qualifying_code: str
    placement_index: int
    age: Optional[int] = Field(None, ge=0)

class GuestCountInfoAPI(BaseModel):
    guest_counts: List[GuestCountDetailAPI] = Field(..., min_length=1)
    adults: Optional[int] = None
    children: Optional[int] = None
    index: Optional[Union[int, str]] = None


class GuestInfo(BaseModel):
    placement: GuestPlacementRef
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    citizenship: Optional[str] = None
    sex: Optional[Literal["male", "female"]] = None

class ServiceReservation(BaseModel):
    code: str
    quantity: Optional[int] = Field(None, ge=1)

class GuaranteeReservation(BaseModel):
    code: str
    success_url: AnyHttpUrl
    decline_url: AnyHttpUrl

class CustomerContactPhone(BaseModel):
    phone_number: str

class CustomerContactEmail(BaseModel):
    email_address: str

class CustomerContactInfo(BaseModel):
    phones: List[CustomerContactPhone] = Field(..., min_length=1)
    emails: List[CustomerContactEmail] = Field(..., min_length=1)

class CustomerReservation(BaseModel):
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    comment: Optional[str] = Field(None)
    confirm_sms: bool
    subscribe_email: bool
    contact_info: CustomerContactInfo

class RoomStayReservation(BaseModel):
    stay_dates: DateRangeStay
    room_types: List[RoomTypeReservation] = Field(..., min_length=1)
    rate_plans: List[RatePlanReservation] = Field(..., min_length=1)
    guest_count_info: GuestCountInfoAPI
    guests: List[GuestInfo] = Field(..., min_length=1)
    services: List[ServiceReservation] = Field(default_factory=list)

class PointOfSale(BaseModel):
    source_url: AnyHttpUrl
    integration_key: Optional[str] = None

class HotelReservationVerification(BaseModel):
    cancellation_code: str

class HotelReservationRequestItem(BaseModel):
    hotel_ref: HotelRef
    room_stays: List[RoomStayReservation] = Field(..., min_length=1)
    transfers: List[ServiceReservation] = Field(default_factory=list)
    services: List[ServiceReservation] = Field(default_factory=list)
    number: Optional[str] = None
    verification: Optional[HotelReservationVerification] = None
    guarantee: GuaranteeReservation
    customer: CustomerReservation

class HotelReservationRequest(BaseModel):
    language: str
    hotel_reservations: List[HotelReservationRequestItem] = Field(..., min_length=1)
    currency: constr(min_length=3, max_length=3)
    include_extra_stay_options: Optional[bool] = Field(False)
    include_guarantee_options: Optional[bool] = Field(False)
    point_of_sale: Optional[PointOfSale] = None


# --- hotel_reservation_2 RESPONSE Models ---
# (Существующие модели для hotel_reservation_2 response остаются без изменений)
# ... (все модели от GuestReservationResponse до HotelReservationResponse)

class GuestReservationResponse(GuestInfo):
    ref: str
    city: Optional[str] = None
    region: Optional[str] = None
    postal_code: Optional[str] = None
    count: Optional[int] = None

class RoomTypeReservationPlacementResponse(RoomTypeReservationPlacement):
    rate_plan_code: Union[str, int]
    price_before_tax: float
    price_after_tax: float
    currency: constr(min_length=3, max_length=3)
    capacity: int

class RoomTypeReservationResponse(RoomTypeReservation):
    name: str
    kind: str
    placements: List[RoomTypeReservationPlacementResponse]

class RatePlanReservationResponse(RatePlanReservation):
    name: str
    description: Optional[str] = None
    cancel_penalty_group: RatePlanCancelPenaltyGroupInAvailability # Используем существующую, т.к. структура похожа

class ServicePriceDetail(BaseModel):
    price_before_tax: float
    price_after_tax: float
    currency: constr(min_length=3, max_length=3)
    taxes: List[TaxItem] = Field(default_factory=list)

class ServiceReservationResponse(ServiceReservation):
    name: str
    description: Optional[str] = None
    price: ServicePriceDetail
    charge_type: str
    kind: str
    meal_plan_type: Optional[str] = None
    inclusive: bool
    applicability_type: Optional[str] = None

class ExtraStayCharge(BaseModel):
    base_check_in_time: Optional[str] = None # Формат HH:MM
    base_check_out_time: Optional[str] = None # Формат HH:MM

class ExtraStayOptionDetail(BaseModel):
    price: ServicePriceDetail
    date: str # Формат YYYY-MM-DD
    local_time: str # Формат HH:MM
    forbidden: bool

class ExtraStayChargeOptions(BaseModel):
    early_arrival_rule_description: Optional[str] = None
    late_departure_rule_description: Optional[str] = None
    early_arrival: List[ExtraStayOptionDetail] = Field(default_factory=list)
    late_departure: List[ExtraStayOptionDetail] = Field(default_factory=list)
    base_check_in_time: Optional[str] = None
    base_check_out_time: Optional[str] = None

class RoomStayReservationResponse(RoomStayReservation):
    guests: List[GuestReservationResponse]
    room_types: List[RoomTypeReservationResponse]
    rate_plans: List[RatePlanReservationResponse]
    placement_rates: List[PlacementRateInfo]
    stay_total: PriceInfo
    total: PriceInfo
    services: List[ServiceReservationResponse] = Field(default_factory=list)
    extra_stay_charge: ExtraStayCharge
    extra_stay_charge_options: Optional[ExtraStayChargeOptions] = None
    guest_count_info: GuestCountInfoAPI # Используем существующую

class PrepaymentAmountDetail(BaseModel):
    amount: float
    type: str # e.g., "percent", "fixed"
    currency: constr(min_length=3, max_length=3)

class GuaranteeInfoResponseItem(GuaranteeInfo): # Расширяем существующий GuaranteeInfo
    name: Optional[str] = None
    payment_system_code: Optional[str] = None
    payment_url: Optional[AnyHttpUrl] = None
    texts: Optional[Dict[str, Optional[str]]] = None # e.g. {"description": "...", "payment_system_information": "..."}
    require_prepayment: Optional[bool] = None
    prepayment: Optional[PrepaymentAmountDetail] = None
    payment_system_proxy_code: Optional[str] = None
    name_short: Optional[str] = None
    card_limits: Optional[str] = None # "Unknown type, might be JSON string or simple string"

class GuaranteeOverallInfoResponse(BaseModel):
    guarantees: List[GuaranteeInfoResponseItem]
    status: str # e.g. "accepted"
    prepayment: Optional[PrepaymentAmountDetail] = None
    payable: Optional[PrepaymentAmountDetail] = None


class CustomerReservationResponse(CustomerReservation):
    pass

class HotelReservationResponseItem(BaseModel):
    number: str
    cancellation_code: str
    status: str
    hotel_ref: HotelRef
    room_stays: List[RoomStayReservationResponse]
    guarantee_info: GuaranteeOverallInfoResponse # Используем новую модель
    order_url: Optional[AnyHttpUrl] = None
    total: PriceInfo
    create_date: str # Формат "YYYY-MM-DD HH:MM:SSZ"
    last_modification_date: Optional[str] = None # Формат "YYYY-MM-DD HH:MM:SSZ"
    customer: CustomerReservationResponse
    language: str
    point_of_sale: Optional[PointOfSale] = None
    services: List[ServiceReservationResponse] = Field(default_factory=list)


class HotelReservationResponse(BaseModel):
    hotel_reservations: Optional[List[HotelReservationResponseItem]] = None
    errors: Optional[List[ErrorDetail]] = None
    warnings: Optional[List[WarningDetail]] = None


# --- cancel_reservation_2 REQUEST Models ---
# (Существующие модели для cancel_reservation_2 request остаются без изменений)
# ...
class CancelReservationReason(BaseModel):
    code: str
    text: Optional[str] = None

class CancelReservationVerification(BaseModel):
    cancellation_code: str

class CancelHotelReservationRef(BaseModel):
    number: str
    verification: CancelReservationVerification

class CancelReservationRequestPayload(BaseModel):
    hotel_reservation_refs: List[CancelHotelReservationRef] = Field(..., min_length=1)
    reasons: Optional[List[CancelReservationReason]] = None
    language: str

# --- cancel_reservation_2 RESPONSE Models ---
# (Существующие модели для cancel_reservation_2 response остаются без изменений)
# ...

class CancelledHotelReservationItem(BaseModel):
    number: str
    status: str

class CancelReservationResponsePayload(BaseModel):
    hotel_reservations: Optional[List[CancelledHotelReservationItem]] = None
    errors: Optional[List[ErrorDetail]] = None
    warnings: Optional[List[WarningDetail]] = None

# --- НОВЫЕ МОДЕЛИ ДЛЯ hotel_info RESPONSE ---

class ImageDetail(BaseModel):
    url: AnyHttpUrl

class RoomTypeSizeDetail(BaseModel):
    value: float
    unit: str # e.g., "square_metre"

class AmenityDetail(BaseModel):
    category_code: Optional[str] = None # В примере есть, в описании нет слова category_code
    kind: str
    name: str

class HotelAgeGroupRef(BaseModel): # Ссылка на возрастную группу, используемую в room_types
    code: str

class HotelRoomTypeDetail(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    size: Optional[RoomTypeSizeDetail] = None
    amenities: List[AmenityDetail] = Field(default_factory=list)
    preferences: List[Dict[str, Any]] = Field(default_factory=list) # Структура не ясна, пока Dict
    images: List[ImageDetail] = Field(default_factory=list)
    kind: str # e.g., "room"
    max_adult_occupancy: Optional[int] = None
    max_extra_bed_occupancy: Optional[int] = None
    max_without_bed_occupancy: Optional[int] = None
    max_occupancy: Optional[int] = None
    accommodate_adults_on_extra_bed: Optional[bool] = None
    child_extra_bed_age_groups: List[HotelAgeGroupRef] = Field(default_factory=list)
    child_without_bed_age_groups: List[HotelAgeGroupRef] = Field(default_factory=list)

class HotelServiceCategoryDetail(BaseModel): # Если есть категории сервисов
    code: Optional[str] = None # В примере пустой service_categories
    name: Optional[str] = None

class HotelServiceDetail(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    charge_type: str # e.g., "per_person_per_night"
    kind: str # e.g., "meal"
    meal_plan_type: Optional[str] = None # e.g., "breakfast"
    images: List[ImageDetail] = Field(default_factory=list)
    require_prepayment: Optional[bool] = None # Из примера, но в описании services этого нет
    require_guaranteed_payment: Optional[bool] = None
    applicability_type: Optional[str] = None # e.g., "all_guests"

class CancelPenaltyGroupForHotelInfo(BaseModel): # Структура из hotel_info.rate_plans.cancel_penalty_group
    code: str
    show_description: bool
    # В примере hotel_info нет description и cancel_penalties внутри этой группы,
    # но есть в cancel_penalty_groups на уровне отеля.
    # Если они могут быть здесь, нужно добавить Optional[str] и Optional[List[RatePlanCancelPenalty]]
    description: Optional[str] = None # Добавлено на всякий случай, если API может вернуть
    cancel_penalties: List[RatePlanCancelPenalty] = Field(default_factory=list) # Добавлено

class HotelRatePlanDetail(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    short_description: Optional[str] = None
    currency: Optional[str] = None # В примере есть "USD"
    images: List[ImageDetail] = Field(default_factory=list)
    nonrefundable: Optional[bool] = None
    cancel_penalty_group: CancelPenaltyGroupForHotelInfo # Используем новую, более точную для hotel_info
    full_prepayment: Optional[bool] = None
    promo: Optional[bool] = None # Добавлено из описания hotel_info

class AmenityCategoryDetail(BaseModel):
    code: str
    name: str

class TimeZoneDetail(BaseModel):
    name: str
    offset: str # e.g., "+09:30"

class HotelPolicyDetail(BaseModel):
    check_in_time: Optional[str] = None # e.g., "16:00"
    check_out_time: Optional[str] = None # e.g., "14:00"

class DurationDetail(BaseModel):
    duration: int
    time_unit: str # e.g., "day", "year"

class HotelBookingRuleDetail(BaseModel):
    availability_min_date: Optional[DurationDetail] = None
    availability_max_date: Optional[DurationDetail] = None

class HotelGuaranteeDetail(BaseModel): # Используется в hotel_info.guarantees
    code: str
    primary_guarantee_code: Optional[str] = None
    payment_system_code: Optional[str] = None # e.g., "AT_ARRIVAL"
    type: str # e.g., "cash"
    # name не было в примере для hotel_info.guarantees, но есть в GuaranteeInfo, оставляю Optional
    name: Optional[str] = None


class HotelAddressDetail(BaseModel):
    postal_code: Optional[str] = None
    country_code: Optional[str] = None
    region: Optional[str] = None
    city_name: Optional[str] = None
    address_line: List[str] = Field(default_factory=list)
    remark: Optional[str] = None
    latitude: Optional[str] = None
    longitude: Optional[str] = None

class HotelPhoneDetail(BaseModel):
    phone_number: str
    remark: Optional[str] = None

class HotelEmailDetail(BaseModel):
    email_address: str

class HotelContactInfoDetail(BaseModel):
    addresses: List[HotelAddressDetail] = Field(default_factory=list)
    phones: List[HotelPhoneDetail] = Field(default_factory=list)
    emails: List[HotelEmailDetail] = Field(default_factory=list)

class HotelTransferDetail(BaseModel): # Структура из hotel_info.transfers (если есть)
    kind: Optional[str] = None
    name: Optional[str] = None
    direction: Optional[str] = None
    description: Optional[str] = None
    require_guaranteed_payment: Optional[bool] = None
    endpoint_name: Optional[str] = None
    transfer_code: Optional[str] = None

class HotelVehicleDetail(BaseModel): # Структура из hotel_info.vehicles (если есть)
    vehicle_code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    capacity: Optional[int] = None

class HotelTaxDetail(BaseModel): # Структура из hotel_info.taxes (если есть)
    code: Optional[str] = None
    kind: Optional[str] = None
    # Другие поля, если API их возвращает

class HotelAgeGroupDefinition(BaseModel): # Полное определение возрастной группы
    code: str
    min_age: int
    max_age: int

class HotelInfoHotelDetail(BaseModel): # Основная модель для одного отеля в ответе hotel_info
    code: str
    name: str
    type: Optional[str] = None # e.g., "hotel_alt"
    description: Optional[str] = None
    stars: Optional[float] = None
    currency: Optional[str] = None # e.g., "USD"
    stay_unit_kind: Optional[str] = None # e.g., "night"
    min_guest_age: Optional[int] = None
    last_booking_date: Optional[str] = None # Непонятный формат "0.02:02:14"

    logo: Optional[ImageDetail] = None
    images: List[ImageDetail] = Field(default_factory=list) # Общие изображения отеля

    contact_info: Optional[HotelContactInfoDetail] = None
    timezone: Optional[TimeZoneDetail] = None
    policy: Optional[HotelPolicyDetail] = None
    booking_rules: Optional[HotelBookingRuleDetail] = None

    room_types: List[HotelRoomTypeDetail] = Field(default_factory=list)
    service_categories: List[HotelServiceCategoryDetail] = Field(default_factory=list) # В примере пусто
    services: List[HotelServiceDetail] = Field(default_factory=list)
    rate_plans: List[HotelRatePlanDetail] = Field(default_factory=list)
    rate_plan_categories: List[Dict[str, Any]] = Field(default_factory=list) # В примере пусто, структура неизвестна

    amenity_categories: List[AmenityCategoryDetail] = Field(default_factory=list)
    guarantees: List[HotelGuaranteeDetail] = Field(default_factory=list)

    # cancel_penalty_groups на уровне отеля (из примера hotel_info)
    cancel_penalty_groups: List[CancelPenaltyGroupForHotelInfo] = Field(default_factory=list)

    transfers: List[HotelTransferDetail] = Field(default_factory=list) # В примере пусто
    vehicles: List[HotelVehicleDetail] = Field(default_factory=list) # В примере пусто
    taxes: List[HotelTaxDetail] = Field(default_factory=list) # В примере пусто

    age_groups: List[HotelAgeGroupDefinition] = Field(default_factory=list) # Определения возрастных групп
    promo_rate_plans: Optional[bool] = None # Из описания, в примере не было

    # Поля, которые есть в примере ответа hotel_info, но не в описании параметров:
    # last_booking_date: Optional[str] = None # "0.02:02:14" - формат неясен, пока строка

class HotelInfoResponse(BaseModel):
    hotels: List[HotelInfoHotelDetail] = Field(default_factory=list)
    errors: Optional[List[ErrorDetail]] = None
    warnings: Optional[List[WarningDetail]] = None
