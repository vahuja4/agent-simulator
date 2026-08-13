"""Tool names, verbatim from the Sierra ``toolNames`` registry (design §2).
The one mapping module: the mock, the deterministic assertions, and the
judges all import from here so they can never drift apart.
"""

from __future__ import annotations

# J1 — Make a one-time payment
PAYEE_LIST = "PayeeList"
FUNDING_ACCOUNT_PICKER = "FundingAccountPicker"
ADD_OPTIONS_ONE_TIME_PAYMENT = "AddOptionsOneTimePayment"
ADD_VALIDATE_ONE_TIME_PAYMENT = "AddValidateOneTimePayment"
ADD_ONE_TIME_PAYMENT = "AddOneTimePayment"  # ⚠ submission tool

# J2 — Set up AutoPay
ADD_OPTIONS_AUTOPAY = "AddOptionsAutoPay"
ADD_VALIDATE_AUTOPAY = "AddValidateAutoPay"
ADD_AUTOPAY = "AddAutoPay"  # ⚠ submission tool

# J3 — Modify existing AutoPay
MODIFY_AUTOPAY_PAYEE_LIST = "ModifyAutoPayPayeeList"
GET_AUTOPAY_STATUS = "GetAutoPayStatus"
UPDATE_AUTOPAY_OPTIONS = "UpdateAutoPayOptions"
UPDATE_VALIDATE_AUTOPAY = "UpdateValidateAutoPay"
UPDATE_AUTOPAY = "UpdateAutoPay"  # ⚠ submission tool

# J4 — Cancel AutoPay (shares ModifyAutoPayPayeeList + GetAutoPayStatus with J3)
CANCEL_AUTOPAY_OPTIONS = "CancelAutoPayOptions"
CANCEL_AUTOPAY = "CancelAutoPay"  # ⚠ submission tool

# J5 — Cancel a scheduled one-time payment
GET_CARD_PAYMENT_ACTIVITY = "GetCardPaymentActivity"
GET_CANCEL_PAYMENT_OPTIONS = "GetCancelPaymentOptions"
CANCEL_PAYMENT = "CancelPayment"  # ⚠ submission tool

# Shared
KNOWLEDGE_BASE_SEARCH = "KnowledgeBaseSearch"

J1_TOOLS = (
    PAYEE_LIST,
    FUNDING_ACCOUNT_PICKER,
    ADD_OPTIONS_ONE_TIME_PAYMENT,
    ADD_VALIDATE_ONE_TIME_PAYMENT,
    ADD_ONE_TIME_PAYMENT,
)

J2_TOOLS = (
    PAYEE_LIST,
    ADD_OPTIONS_AUTOPAY,
    FUNDING_ACCOUNT_PICKER,
    ADD_VALIDATE_AUTOPAY,
    ADD_AUTOPAY,
)

J3_TOOLS = (
    MODIFY_AUTOPAY_PAYEE_LIST,
    GET_AUTOPAY_STATUS,
    UPDATE_AUTOPAY_OPTIONS,
    UPDATE_VALIDATE_AUTOPAY,
    UPDATE_AUTOPAY,
)

J4_TOOLS = (
    MODIFY_AUTOPAY_PAYEE_LIST,
    GET_AUTOPAY_STATUS,
    CANCEL_AUTOPAY_OPTIONS,
    CANCEL_AUTOPAY,
)

J5_TOOLS = (
    GET_CARD_PAYMENT_ACTIVITY,
    GET_CANCEL_PAYMENT_OPTIONS,
    CANCEL_PAYMENT,
)

ALL_TOOLS = tuple(
    dict.fromkeys(
        (*J1_TOOLS, *J2_TOOLS, *J3_TOOLS, *J4_TOOLS, *J5_TOOLS, KNOWLEDGE_BASE_SEARCH)
    )
)

# Submission tool → the validate/options counterpart that must have succeeded
# first (the assertion engine keys off this mapping).
VALIDATE_FOR_SUBMIT = {
    ADD_ONE_TIME_PAYMENT: ADD_VALIDATE_ONE_TIME_PAYMENT,
    ADD_AUTOPAY: ADD_VALIDATE_AUTOPAY,
    UPDATE_AUTOPAY: UPDATE_VALIDATE_AUTOPAY,
    CANCEL_AUTOPAY: CANCEL_AUTOPAY_OPTIONS,  # token fetch, not a validate — same gate
    CANCEL_PAYMENT: GET_CANCEL_PAYMENT_OPTIONS,
}


# The five §3 validate→submit pairings as structured metadata for the
# deterministic assertion engine. Per pairing:
# - counterpart:   the validate/options tool that must succeed before submit
#                  (mirrors VALIDATE_FOR_SUBMIT)
# - id_result_key: field of the counterpart's RESULT whose value must appear
#                  under the same key in the submit's ARGUMENTS — the staged
#                  pending object's identity (Sierra threads formId/token this
#                  way). Requires results; when absent the engine degrades to
#                  match_arg_keys.
# - match_arg_keys: argument fields shared by counterpart and submit calls,
#                  used to match the pair when results are unavailable
#                  (empty = ordering-only fallback).
# - options_tool:  the options tool whose fresh fetch must precede the
#                  counterpart for the currently selected card (None for the
#                  token-fetch flows, which have no amount options).
SUBMIT_PAIRINGS: dict[str, dict[str, object]] = {
    ADD_ONE_TIME_PAYMENT: {
        "counterpart": ADD_VALIDATE_ONE_TIME_PAYMENT,
        "id_result_key": "formId",
        "match_arg_keys": (),
        "options_tool": ADD_OPTIONS_ONE_TIME_PAYMENT,
    },
    ADD_AUTOPAY: {
        "counterpart": ADD_VALIDATE_AUTOPAY,
        "id_result_key": "formId",
        "match_arg_keys": (),
        "options_tool": ADD_OPTIONS_AUTOPAY,
    },
    UPDATE_AUTOPAY: {
        "counterpart": UPDATE_VALIDATE_AUTOPAY,
        "id_result_key": "formId",
        "match_arg_keys": ("token", "repeatingModelId"),
        "options_tool": UPDATE_AUTOPAY_OPTIONS,
    },
    CANCEL_AUTOPAY: {
        "counterpart": CANCEL_AUTOPAY_OPTIONS,
        "id_result_key": "token",
        "match_arg_keys": ("repeatingModelId",),
        "options_tool": None,
    },
    CANCEL_PAYMENT: {
        "counterpart": GET_CANCEL_PAYMENT_OPTIONS,
        "id_result_key": "paymentId",
        "match_arg_keys": ("paymentId",),
        "options_tool": None,
    },
}

SUBMIT_TOOLS = tuple(SUBMIT_PAIRINGS)
