from ..services import visit
class VisitController:
    quotas=staticmethod(visit.list_quotas)
    set_quotas=staticmethod(visit.set_quotas)
    rosters=staticmethod(visit.list_rosters)
    roster=staticmethod(visit.get_roster)
    create_roster=staticmethod(visit.create_roster)
    suggest=staticmethod(visit.suggest_counts_for_run)
