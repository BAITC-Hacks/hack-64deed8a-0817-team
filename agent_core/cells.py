"""Audience cells = (current_tariff, arpu_segment) with size and mean predicted ARPU."""


def build_cells(profile):
    g = (profile.groupby(["current_tariff", "arpu_segment"], observed=True)
         .agg(size=("ID_NUMBER", "size"), arpu=("predicted_arpu", "mean"))
         .reset_index())
    return {
        (r.current_tariff, r.arpu_segment): {"size": int(r.size), "arpu": float(r.arpu)}
        for r in g.itertuples(index=False)
    }
