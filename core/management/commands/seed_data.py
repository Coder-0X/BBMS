"""
One-shot seed command: populate ComponentType catalog, TestDefinition list, and state transitions.
Run: python manage.py seed_data
"""
from django.core.management.base import BaseCommand
from django.db import transaction


COMPONENT_TYPES = [
    # code, name, class, shelf_life_hours, temp_min, temp_max
    ('RBC-SAG',   'Red Blood Cells in SAG-M',          'RBC',  1008, 2.0,  6.0),
    ('RBC-CPD',   'Red Blood Cells in CPD',             'RBC',  504,  2.0,  6.0),
    ('RBC-LR',    'Leukoreduced Red Blood Cells',       'RBC',  1008, 2.0,  6.0),
    ('RBC-IRR',   'Irradiated Red Blood Cells',         'RBC',  120,  2.0,  6.0),
    ('RBC-WAS',   'Washed Red Blood Cells',             'RBC',  24,   2.0,  6.0),
    ('FFP-FZ',    'Fresh Frozen Plasma',                'FFP',  8760, -25.0,-18.0),
    ('FFP-MB',    'Methylene Blue Treated Plasma',      'FFP',  8760, -25.0,-18.0),
    ('PLT-PC',    'Pooled Platelet Concentrate',        'PLT',  120,  20.0, 24.0),
    ('PLT-APH',   'Apheresis Platelets',                'PLT',  120,  20.0, 24.0),
    ('PLT-LR',    'Leukoreduced Platelets',             'PLT',  120,  20.0, 24.0),
    ('CRYO-PREC', 'Cryoprecipitate',                   'CRYO', 8760, -25.0,-18.0),
    ('WB-FRH',    'Fresh Whole Blood',                 'WB',   24,   2.0,  6.0),
    ('GRAN-APH',  'Granulocytes (Apheresis)',           'GRAN', 24,   20.0, 24.0),
]

TTI_TESTS = [
    ('HIV_AG_AB', 'HIV Ag/Ab Combo', 'HIV-1/2', 'ELISA', True),
    ('HIV_NAT',   'HIV Nucleic Acid Test', 'HIV-1', 'NAT', True),
    ('HBsAg',     'Hepatitis B Surface Antigen', 'HBV', 'ELISA', True),
    ('HBV_NAT',   'HBV Nucleic Acid Test', 'HBV', 'NAT', True),
    ('anti_HCV',  'Hepatitis C Antibody', 'HCV', 'ELISA', True),
    ('HCV_NAT',   'HCV Nucleic Acid Test', 'HCV', 'NAT', True),
    ('VDRL',      'Syphilis (VDRL/RPR)', 'T. pallidum', 'RPR', True),
    ('anti_HBc',  'Hepatitis B Core Antibody', 'HBV', 'ELISA', False),
    ('HTLV',      'HTLV-I/II Antibody', 'HTLV', 'ELISA', False),
    ('malaria',   'Malaria Antibody', 'Plasmodium', 'ELISA', False),
    ('Chagas',    'T. cruzi Antibody (Chagas)', 'T. cruzi', 'ELISA', False),
]


class Command(BaseCommand):
    help = 'Seed blood bank reference data: ComponentTypes, TestDefinitions, state transitions, demo branch, roles'

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_components()
        self._seed_tests()
        self._seed_transitions()
        self._seed_demo_branch()
        self._seed_roles()

    def _seed_components(self):
        from inventory.models import ComponentType
        count = 0
        for code, name, cls, shelf_h, tmin, tmax in COMPONENT_TYPES:
            _, created = ComponentType.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'component_class': cls,
                    'shelf_life_hours': shelf_h,
                    'storage_temp_min_c': tmin,
                    'storage_temp_max_c': tmax,
                }
            )
            if created:
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  {count} ComponentType(s) created.'))

    def _seed_tests(self):
        from transfusion.models import TestDefinition
        count = 0
        for code, name, pathogen, method, mandatory in TTI_TESTS:
            _, created = TestDefinition.objects.get_or_create(
                test_code=code,
                defaults={'name': name, 'pathogen': pathogen, 'method': method, 'mandatory': mandatory}
            )
            if created:
                count += 1
        self.stdout.write(self.style.SUCCESS(f'  {count} TestDefinition(s) created.'))

    def _seed_transitions(self):
        from inventory.state_machine import seed_transitions
        seed_transitions()
        self.stdout.write(self.style.SUCCESS('  State transitions seeded.'))

    def _seed_demo_branch(self):
        from core.models import Branch, RefFacility
        from compliance.models import ComplianceJurisdiction, ComplianceRuleset
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Create minimal jurisdiction if none exist
        jur, _ = ComplianceJurisdiction.objects.get_or_create(
            country_code='XX',
            defaults={'name': 'Demo Jurisdiction'},
        )

        # ComplianceRuleset requires created_by — use first superuser or skip
        superuser = User.objects.filter(is_superuser=True).first()
        ruleset = None
        if superuser:
            ruleset, _ = ComplianceRuleset.objects.get_or_create(
                jurisdiction=jur,
                version='1.0',
                defaults={
                    'effective_from': '2024-01-01',
                    'status': 'active',
                    'created_by': superuser,
                }
            )

        branch, created = Branch.objects.get_or_create(
            facility_code='DEM',
            defaults={
                'name': 'Demo Blood Bank',
                'address': '1 Hospital Road, Demo City',
                'timezone': 'UTC',
                'active': True,
                'jurisdiction': jur,
                'active_ruleset': ruleset,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS('  Demo branch created: Demo Blood Bank (DEM).'))
            RefFacility.objects.get_or_create(
                pk='DEM',
                defaults={'facility_code': 'DEM', 'name': branch.name, 'branch': branch, 'last_serial': 0},
            )
        else:
            self.stdout.write(f'  Branch DEM already exists.')

    def _seed_roles(self):
        from accounts.models import Role, Permission

        PERMISSIONS = [
            ('donor.register', 'Register new donors'),
            ('donor.view', 'View donor records'),
            ('patient.register', 'Register new patients'),
            ('patient.blood_group', 'Record blood group'),
            ('patient.special_requirement', 'Set special transfusion requirements'),
            ('patient.view', 'View patient records'),
            ('unit.process', 'Process blood units'),
            ('unit.status_change', 'Change unit status'),
            ('unit.release', 'Issue blood units to patients'),
            ('unit.emergency_release', 'Authorize emergency blood release'),
            ('donor.blood_group', 'Record donor blood group (ABO/Rh)'),
            ('test.perform', 'Perform TTI and crossmatch tests'),
            ('test.crossmatch', 'Perform crossmatch'),
            ('recall.manage', 'Initiate blood unit recall'),
            ('report.view', 'View reports'),
            ('audit.view', 'View audit log'),
            ('reagent.manage', 'Manage reagents and lot numbers'),
            ('mtp.activate', 'Activate Massive Transfusion Protocol'),
            ('neonatal.manage', 'Create and manage neonatal transfusion orders'),
        ]

        ROLES = {
            'Donor Technician': ['donor.register', 'donor.view', 'unit.process'],
            'Lab Technologist': ['test.perform', 'test.crossmatch', 'patient.blood_group', 'donor.blood_group', 'patient.view', 'donor.view', 'reagent.manage', 'neonatal.manage'],
            'Blood Bank Officer': [
                'donor.view', 'patient.view', 'unit.status_change', 'unit.release',
                'report.view', 'recall.manage', 'neonatal.manage',
            ],
            'Physician': ['patient.register', 'patient.view', 'unit.emergency_release', 'patient.special_requirement', 'mtp.activate', 'neonatal.manage'],
            'Administrator': [p[0] for p in PERMISSIONS],
        }

        perm_count = 0
        for code, desc in PERMISSIONS:
            _, created = Permission.objects.get_or_create(code=code, defaults={'description': desc})
            if created:
                perm_count += 1

        role_count = 0
        for role_name, perm_codes in ROLES.items():
            role, created = Role.objects.get_or_create(
                name=role_name,
                defaults={'description': f'Default {role_name} role', 'branch_scoped': True},
            )
            if created:
                perms = Permission.objects.filter(code__in=perm_codes)
                role.permissions.set(perms)
                role_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'  {perm_count} Permission(s) and {role_count} Role(s) created.'
        ))
