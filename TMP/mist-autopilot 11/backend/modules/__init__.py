from .roam_guard import RoamGuardModule
from .sle_sentinel import SLESentinelModule
from .config_drift import ConfigDriftModule
from .rf_fingerprint import RFFingerprintModule
from .secure_scope import SecureScopeModule
from .client_experience import ClientExperienceModule
from .ap_lifecycle import APLifecycleModule
from .wan_sentinel import WANSentinelModule
from .sub_monitor import SUBMonitorModule
from .minis_monitor import MinisMonitorModule
from .auth_guard import AuthGuardModule

# Registry — add new modules here and they appear in the dashboard automatically
ALL_MODULES = [
    RoamGuardModule(),
    SLESentinelModule(),
    ConfigDriftModule(),
    RFFingerprintModule(),
    SecureScopeModule(),
    ClientExperienceModule(),
    APLifecycleModule(),
    WANSentinelModule(),
    SUBMonitorModule(),
    MinisMonitorModule(),
    AuthGuardModule(),
]
