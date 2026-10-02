from portfolio_cockpit.scoring.drift import initial_quality_drift
from portfolio_cockpit.scoring.portfolio_risk import portfolio_impact
from portfolio_cockpit.scoring.quality import z_to_quality_score


def main():
    print("Portfolio Cockpit Phase 1 demo")
    print("Quality Drift baseline:", initial_quality_drift())
    print("Peer-median Fundamental Quality:", z_to_quality_score(0.0))
    print("5% position / -30% shock:", f"{portfolio_impact(0.05, -0.30):.1%}")


if __name__ == "__main__":
    main()
