class OrderManager:
    """Reserved for a later execution phase."""

    def place_order(self, *args, **kwargs):
        raise RuntimeError("Live order placement is disabled in Phase 1.")
