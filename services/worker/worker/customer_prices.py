"""Worker counterpart to API customer-price visibility; retain all stored evidence."""


def is_customer_price(source, observation):
    return not (source == "yuyutei" and observation.promotion_state == "sale")


def customer_price_series(series, source):
    if not series or not is_customer_price(source, series[-1]):
        return []
    return [obs for obs in series if is_customer_price(source, obs)]


def customer_latest_prices(latest_by_card):
    return {
        card_id: {key: obs for key, obs in prices.items() if is_customer_price(key[0], obs)}
        for card_id, prices in latest_by_card.items()
    }
