"""Polskie opisy kodów diagnostycznych silnika."""

import re

RUNTIME_MESSAGES = {
    "attempt_store_failed": "Nie udało się zapisać próby sterowania.",
    "background_plan_failed": "Nie udało się przeliczyć planu ładowania.",
    "battery_low_soc_unavailable": "Brak poprawnego odczytu dolnego progu SoC baterii.",
    "command_failed": "Home Assistant nie potwierdził wykonania polecenia falownika.",
    "current_policy_store_failed": "Nie udało się zapisać stanu regulacji prądu ładowania.",
    "future_attempt_ledger": "Historia prób sterowania zawiera zapis z przyszłości.",
    "grid_outcome_store_failed": "Nie udało się zapisać wyniku polecenia ładowania z sieci.",
    "invalid_attempt_ledger": "Zapis historii prób sterowania jest nieprawidłowy.",
    "last_moment_charge_need_guard": "Po ponownym przeliczeniu zapotrzebowania EMS wstrzymał zmianę prądu ładowania.",
    "last_moment_current_guard": "EMS wstrzymał zmianę prądu ładowania z sieci po końcowej kontroli bezpieczeństwa.",
    "last_moment_dispatch_guard": "EMS wstrzymał wysłanie nastawy prądu ładowania po ponownym sprawdzeniu warunków.",
    "last_moment_gc_guard": "EMS wstrzymał włączenie ładowania z sieci po końcowej kontroli warunków.",
    "last_moment_grid_step_guard": "EMS wstrzymał zwiększenie prądu ładowania z sieci. Żądana nastawa przekroczyła limit wyliczony tuż przed wysłaniem polecenia.",
    "last_moment_initial_start_guard": "EMS wstrzymał rozpoczęcie ładowania po końcowej kontroli warunków startu.",
    "last_moment_initial_window_guard": "EMS wstrzymał zmianę nastawy po kontroli okna rozpoczęcia ładowania.",
    "last_moment_safety_direction_guard": "EMS odrzucił zmianę nastawy niezgodną z kierunkiem działania ochronnego.",
    "last_moment_tariff_program_guard": "EMS wstrzymał zapis programu taryfowego po końcowej kontroli warunków.",
    "load_profile_unavailable": "Nie udało się odczytać profilu zużycia energii.",
    "native_report_shutdown_failed": "Nie udało się poprawnie zamknąć połączenia odbierającego pomiary.",
    "ownership_conflict": "Wykryto inny sterownik. EMS pozostaje w trybie obserwacji.",
    "ownership_conflict_store_failed": "Wykryto inny sterownik i nie udało się zapisać stanu konfliktu.",
    "periodic_store_failed": "Nie udało się zapisać bieżącego stanu silnika.",
    "plan_store_failed": "Nie udało się zapisać planu ładowania.",
    "restored_active_preflight_failed": "Po uruchomieniu nie wznowiono sterowania, ponieważ nie potwierdzono wymaganych warunków.",
    "safety_current_intent_guard": "EMS wstrzymał zmianę prądu po kontroli bezpieczeństwa.",
    "stale_planning_snapshot": "Dane użyte do obliczenia planu straciły aktualność.",
    "top_balance_restore_invalid": "Nie można było wznowić zapisanego wyrównywania ogniw.",
}


def runtime_message(code):
    """Zwróć kod i opis bez treści wyjątku ani danych instalacji."""
    code = code.split(":", 1)[0]
    if not re.fullmatch(r"[a-z][a-z_0-9]{0,79}", code):
        code = "unknown_runtime_error"
    if re.fullmatch(r"last_moment_[a-z_]+_guard", code):
        fallback = "EMS wstrzymał polecenie po końcowej kontroli warunków sterowania."
    else:
        fallback = "Silnik zgłosił błąd. Sprawdź diagnostykę."
    return code, RUNTIME_MESSAGES.get(code, fallback)
