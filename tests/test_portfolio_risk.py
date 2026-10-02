from portfolio_cockpit.scoring.portfolio_risk import portfolio_impact


def test_five_percent_position_down_thirty_percent():
    assert portfolio_impact(0.05, -0.30) == -0.015
