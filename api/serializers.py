"""
DRF serializers — read-only by default for safety.
Write operations go through the domain modules (issue.py, testing.py, etc.)
to enforce all safety invariants.
"""
from rest_framework import serializers

from donors.models import Donor, Donation
from inventory.models import BloodUnit, ComponentType, UnitStatusEvent
from patients.models import Patient, PatientBloodGroup, PatientAntibody, PatientTransfusionRequirement
from transfusion.models import (
    Sample, DonationTestResult, BloodRequest,
    Crossmatch, IssueTransaction, EmergencyRelease,
)
from core.models import Alert, Branch


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'facility_code']


class ComponentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComponentType
        fields = ['code', 'name', 'component_class', 'shelf_life_hours',
                  'storage_temp_min_c', 'storage_temp_max_c']


class DonorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donor
        fields = ['id', 'sex', 'dob', 'blood_group_abo', 'blood_group_rh',
                  'deferral_status', 'total_donations', 'last_donation_date']


class DonationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Donation
        fields = ['id', 'donor', 'donation_type', 'volume_ml', 'donated_at', 'branch']


class BloodUnitSerializer(serializers.ModelSerializer):
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = BloodUnit
        fields = [
            'id', 'did', 'component_class', 'component_type',
            'abo_type', 'rh_d_type', 'status', 'version',
            'expiry_datetime', 'is_expired', 'owner_branch',
            'is_leukoreduced', 'is_irradiated', 'is_cmv_negative', 'is_washed',
            'antigen_negative_set',
        ]

    def get_is_expired(self, obj):
        return obj.is_expired()


class UnitStatusEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitStatusEvent
        fields = ['from_status', 'to_status', 'reason', 'actor', 'occurred_at']


class PatientSerializer(serializers.ModelSerializer):
    current_abo = serializers.SerializerMethodField()
    current_rh  = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = ['id', 'mpi_uid', 'sex', 'dob', 'record_status', 'current_abo', 'current_rh']

    def get_current_abo(self, obj):
        bg = obj.current_blood_group()
        return bg.abo if bg else None

    def get_current_rh(self, obj):
        bg = obj.current_blood_group()
        return bg.rh_d if bg else None


class PatientAntibodySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientAntibody
        fields = ['specificity', 'antigen_system', 'clinical_significance', 'status', 'evanescent']


class PatientTransfusionRequirementSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientTransfusionRequirement
        fields = ['requirement', 'antigen_spec', 'reason', 'active']


class SampleSerializer(serializers.ModelSerializer):
    is_valid = serializers.SerializerMethodField()

    class Meta:
        model = Sample
        fields = ['id', 'accession_number', 'patient', 'donor', 'sample_type',
                  'collected_at', 'validity_expiry', 'is_valid', 'abo_confirmation_status']

    def get_is_valid(self, obj):
        return obj.is_valid()


class BloodRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = BloodRequest
        fields = [
            'id', 'patient', 'branch', 'component_class', 'units_requested',
            'units_crossmatched', 'units_transfused', 'urgency',
            'requested_ts', 'outcome', 'special_requirements_snapshot',
        ]


class CrossmatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Crossmatch
        fields = ['id', 'sample', 'blood_unit', 'request', 'method', 'result',
                  'tech', 'performed_at']


class IssueTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueTransaction
        fields = ['id', 'blood_unit', 'patient', 'request', 'issued_by',
                  'issued_at', 'abo_check_passed', 'crossmatch', 'emergency_release']


class AlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alert
        fields = ['id', 'alert_type', 'severity', 'message', 'created_at',
                  'acknowledged_at', 'branch']
