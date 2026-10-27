"""Native installation and one-time read-only legacy import preview."""

import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN
from .control.models import PlantConfiguration
from .legacy import build_preview, detect_legacy, SENSOR_KEYS

PLANT_UID = "hpvc-primary"


def capture_legacy(hass):
    return {
        state.entity_id: str(state.state)
        for state in hass.states.async_all()
        if state.entity_id.startswith(
            (
                "input_boolean.hpvc_",
                "input_number.hpvc_",
                "input_text.hpvc_",
                "input_select.hpvc_",
                "input_button.hpvc_",
            )
        )
    }


class HpvcConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.preview = None

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(PLANT_UID)
        self._abort_if_unique_id_configured()
        errors = {}
        if user_input is not None:
            if user_input.get("import_legacy", False):
                self.preview = build_preview(capture_legacy(self.hass), PLANT_UID)
                if self.preview.issues:
                    errors["base"] = "invalid_legacy"
                else:
                    return await self.async_step_legacy_preview()
            else:
                try:
                    count = user_input.get("inverter_count", 0)
                    if type(count) not in (int, float) or count != int(count):
                        raise ValueError("non-integer count")
                    config = PlantConfiguration(
                        PLANT_UID,
                        inverter_count=int(count),
                        **{key: user_input.get(key, "").strip() for key in SENSOR_KEYS},
                    )
                    return self.async_create_entry(
                        title="Home PV Control",
                        data={
                            "plant_uid": PLANT_UID,
                            "initial_configuration": config.to_dict(),
                        },
                    )
                except (ValueError, TypeError):
                    errors["base"] = "invalid_configuration"
        schema = vol.Schema(
            {
                vol.Optional("import_legacy", default=False): bool,
                vol.Optional("inverter_count", default=0): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=10)
                ),
                **{vol.Optional(key, default=""): str for key in SENSOR_KEYS},
            }
        )
        detail = (
            "; ".join(
                f"{issue.entity_id}: {issue.reason}" for issue in self.preview.issues
            )
            if self.preview and self.preview.issues
            else "none"
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "legacy_state": detect_legacy(capture_legacy(self.hass)),
                "import_errors": detail,
            },
        )

    async def async_step_legacy_preview(self, user_input=None):
        if self.preview is None:
            return await self.async_step_user()
        if user_input is not None and user_input.get("confirm", False):
            latest = build_preview(capture_legacy(self.hass), PLANT_UID)
            if latest.fingerprint != self.preview.fingerprint or latest.issues:
                self.preview = latest
                return self.async_show_form(
                    step_id="legacy_preview",
                    data_schema=vol.Schema(
                        {vol.Required("confirm", default=False): bool}
                    ),
                    errors={"base": "legacy_changed"},
                    description_placeholders={
                        "controller_count": str(
                            latest.candidate.inverter_count
                            if latest.candidate
                            else "invalid"
                        )
                    },
                )
            return self.async_create_entry(
                title="Home PV Control",
                data={
                    "plant_uid": PLANT_UID,
                    "initial_configuration": self.preview.candidate.to_dict(),
                    "legacy_import": self.preview.to_dict(),
                },
            )
        return self.async_show_form(
            step_id="legacy_preview",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            description_placeholders={
                "controller_count": str(self.preview.candidate.inverter_count)
            },
        )
