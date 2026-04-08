class Battery_Bus:
    def __init__(self, veh_setup):
        self.SOC = []
        self.SOC.append(veh_setup['Batterie Start SOC'])
        self.eta = veh_setup['Batterie eta']
        self.capacity = veh_setup['Batterie Kapazitaet']

    def calculate_eta(self, M_trac, n_trac):
        if M_trac * n_trac < 0:
            eta_battery = self.eta
        else:
            eta_battery = 1 / self.eta

        return eta_battery
# SOC wird aktuell falsch berechnet. Entweder kapazität in joule angeben oder e_el_bat in wh umrechnen
    def calculate_SOC(self, E_el_bat):
        SOC = self.SOC[-1] - (E_el_bat  / self.capacity)
        self.SOC.append(SOC)
    # hier kann in zukunft der Batteriewirkungsgrad dynamisch berechnet werden