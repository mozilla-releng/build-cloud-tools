CANCEL_STATUS_CODES = ["capacity-oversubscribed", "price-too-low",
                       "capacity-not-available"]
TERMINATED_BY_AWS_STATUS_CODES = [
    "instance-terminated-by-price",
    "instance-terminated-capacity-oversubscribed",
]
IGNORABLE_STATUS_CODES = CANCEL_STATUS_CODES + TERMINATED_BY_AWS_STATUS_CODES \
    + ["bad-parameters", "canceled-before-fulfillment", "fulfilled",
       "instance-terminated-by-user", "pending-evaluation",
       "pending-fulfillment"]
