PALETTE = [
    "#58a6ff", "#f85149", "#3fb950", "#d29922", "#a371f7",
    "#39c5cf", "#db61a2", "#e3b341", "#ff7b72", "#7ee787",
    "#79c0ff", "#ffa657", "#d2a8ff", "#56d364", "#f0883e",
    "#bc8cff", "#4ac26b", "#ffab70", "#ff9bce", "#6cb6ff",
    "#e5534b", "#46954a", "#c69026", "#8957e5", "#1f6feb",
    "#da3633", "#238636", "#9e6a03", "#6639ba", "#0969da",
    "#a40e26", "#1a7f37", "#7d4e00", "#5e39b5", "#0550ae",
    "#ffb3b3", "#b3ffb3", "#b3b3ff", "#ffe066", "#66e0ff",
    "#ff9966", "#99ff99", "#9966ff", "#ffcc99", "#99ccff",
    "#cc99ff", "#ff6699", "#66ffcc", "#cccc99", "#cc6699",
]


def color_for(user):
    if user is None or not getattr(user, "pk", None):
        return PALETTE[0]
    return PALETTE[user.pk % len(PALETTE)]


def color_for_id(user_id):
    if not user_id:
        return PALETTE[0]
    return PALETTE[user_id % len(PALETTE)]
