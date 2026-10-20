from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from booking.tenancy.models import Bed
from booking.tenancy.models import BusinessType
from booking.tenancy.models import DailyRate
from booking.tenancy.models import Inventory
from booking.tenancy.models import InventoryMode
from booking.tenancy.models import Membership
from booking.tenancy.models import MembershipRole
from booking.tenancy.models import Organization
from booking.tenancy.models import Property
from booking.tenancy.models import RatePlan
from booking.tenancy.models import RateRestriction
from booking.tenancy.models import Season
from booking.tenancy.models import Unit
from booking.tenancy.models import UnitType
from booking.tenancy.models import UnitTypeKind
from booking.users.models import User


@pytest.mark.django_db
def test_property_slug_is_unique_inside_organization():
    organization = Organization.objects.create(name="Balkans Hotels", slug="balkans")
    Property.objects.create(
        organization=organization,
        name="City Hotel",
        slug="city-hotel",
        business_type=BusinessType.OTL_S,
    )

    with pytest.raises(IntegrityError):
        Property.objects.create(
            organization=organization,
            name="Another City Hotel",
            slug="city-hotel",
            business_type=BusinessType.OTL_S,
        )


@pytest.mark.django_db
def test_same_property_slug_can_be_used_in_different_organizations():
    first = Organization.objects.create(name="First", slug="first")
    second = Organization.objects.create(name="Second", slug="second")

    Property.objects.create(organization=first, name="Main", slug="main")
    Property.objects.create(organization=second, name="Main", slug="main")

    assert Property.objects.filter(slug="main").count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_membership_can_be_organization_or_property_scoped():
    user = User.objects.create_user(username="owner")
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )

    organization_membership = Membership.objects.create(
        organization=organization,
        user=user,
        role=MembershipRole.OWNER,
    )
    property_membership = Membership.objects.create(
        organization=organization,
        property=property_,
        user=user,
        role=MembershipRole.MANAGER,
    )

    assert organization_membership.property_id is None
    assert property_membership.property == property_
    assert user.organization_memberships.count() == 2  # noqa: PLR2004


@pytest.mark.django_db
def test_inventory_tree_is_scoped_to_property():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
        kind=UnitTypeKind.ROOM,
        inventory_mode=InventoryMode.UNIT,
        capacity_per_unit=2,
    )
    unit = Unit.objects.create(
        property=property_,
        unit_type=unit_type,
        code="101",
    )
    bed = Bed.objects.create(unit=unit, code="101-A")
    inventory = Inventory.objects.create(
        property=property_,
        unit_type=unit_type,
        date=date(2026, 11, 1),
        total_capacity=10,
        blocked_capacity=2,
    )

    assert unit_type.property == property_
    assert unit.property == property_
    assert bed.unit == unit
    assert inventory.sellable_capacity == 8  # noqa: PLR2004


@pytest.mark.django_db
def test_unit_type_code_is_unique_inside_property():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )

    with pytest.raises(IntegrityError):
        UnitType.objects.create(
            property=property_,
            name="Another Standard Room",
            code="standard-room",
        )


@pytest.mark.django_db
def test_unit_and_inventory_reject_cross_property_relations():
    first_organization = Organization.objects.create(name="First", slug="first")
    second_organization = Organization.objects.create(name="Second", slug="second")
    first_property = Property.objects.create(
        organization=first_organization,
        name="First Hotel",
        slug="first-hotel",
    )
    second_property = Property.objects.create(
        organization=second_organization,
        name="Second Hotel",
        slug="second-hotel",
    )
    unit_type = UnitType.objects.create(
        property=first_property,
        name="Standard Room",
        code="standard-room",
    )

    unit = Unit(property=second_property, unit_type=unit_type, code="201")
    with pytest.raises(ValidationError):
        unit.full_clean()

    inventory = Inventory(
        property=second_property,
        unit_type=unit_type,
        date=date(2026, 11, 1),
        total_capacity=1,
    )
    with pytest.raises(ValidationError):
        inventory.full_clean()


@pytest.mark.django_db
def test_inventory_cannot_have_more_blocked_than_total_capacity():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )
    inventory = Inventory(
        property=property_,
        unit_type=unit_type,
        date=date(2026, 11, 1),
        total_capacity=2,
        blocked_capacity=3,
    )

    with pytest.raises(ValidationError):
        inventory.full_clean()


@pytest.mark.django_db
def test_rate_plan_and_daily_rate_are_scoped_to_property():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Breakfast Included",
        code="breakfast-included",
    )
    daily_rate = DailyRate.objects.create(
        rate_plan=rate_plan,
        date=date(2026, 11, 1),
        amount="1500.00",
        min_nights=1,
        max_nights=5,
    )

    assert rate_plan.unit_type == unit_type
    assert daily_rate.rate_plan == rate_plan


@pytest.mark.django_db
def test_rate_plan_rejects_unit_type_from_another_property():
    first_organization = Organization.objects.create(name="First", slug="first")
    second_organization = Organization.objects.create(name="Second", slug="second")
    first_property = Property.objects.create(
        organization=first_organization,
        name="First Hotel",
        slug="first-hotel",
    )
    second_property = Property.objects.create(
        organization=second_organization,
        name="Second Hotel",
        slug="second-hotel",
    )
    unit_type = UnitType.objects.create(
        property=first_property,
        name="Standard Room",
        code="standard-room",
    )
    rate_plan = RatePlan(
        property=second_property,
        unit_type=unit_type,
        name="Invalid Rate",
        code="invalid-rate",
    )

    with pytest.raises(ValidationError):
        rate_plan.full_clean()


@pytest.mark.django_db
def test_rate_plan_code_is_unique_inside_property():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )
    RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Breakfast Included",
        code="breakfast-included",
    )

    with pytest.raises(IntegrityError):
        RatePlan.objects.create(
            property=property_,
            unit_type=unit_type,
            name="Another Breakfast Included",
            code="breakfast-included",
        )


@pytest.mark.django_db
def test_season_and_daily_rate_validate_date_and_night_ranges():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible",
    )

    season = Season(
        property=property_,
        name="Summer",
        code="summer",
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 1),
    )
    with pytest.raises(ValidationError):
        season.full_clean()

    daily_rate = DailyRate(
        rate_plan=rate_plan,
        date=date(2026, 8, 10),
        amount="1500.00",
        min_nights=4,
        max_nights=2,
    )
    with pytest.raises(ValidationError):
        daily_rate.full_clean()


@pytest.mark.django_db
def test_rate_restriction_code_is_unique_per_date_and_plan():
    organization = Organization.objects.create(name="Balkans", slug="balkans")
    property_ = Property.objects.create(
        organization=organization,
        name="Main Hotel",
        slug="main-hotel",
    )
    unit_type = UnitType.objects.create(
        property=property_,
        name="Standard Room",
        code="standard-room",
    )
    rate_plan = RatePlan.objects.create(
        property=property_,
        unit_type=unit_type,
        name="Flexible",
        code="flexible",
    )
    restriction_data = {
        "rate_plan": rate_plan,
        "date": date(2026, 8, 10),
        "stop_sell": True,
    }
    RateRestriction.objects.create(**restriction_data)

    with pytest.raises(IntegrityError):
        RateRestriction.objects.create(**restriction_data)
