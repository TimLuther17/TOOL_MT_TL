import numpy as np


TAKTRATE = 1.0


class LD_Bus:
    def __init__(self, Name):
        self.axle_ratio_reso = 200
        self.ID = Name
        self.M_trac = []

        self.M_total = []
        self.P_total = []
        self.E_total = []
        self.Torque_split_opt = []

        self.M_brake_mech = []

        self.n_trac = []

        self.P_total_opt_eta = []
        self.M_slope = []
        self.M_resist = []
        self.M_inertial = []
        self.M_drag = []
        self.P_slope = []
        self.P_resist = []
        self.P_inertial = []
        self.P_drag = []
        self.M_rec = []
        self.E_el_mot = []
        self.E_el_bat = []
        self.P_el_mot = []
        self.P_el_bat = []
        self.distance = []

        self.g = 9.81  # Erdanziehungskraft
        self.rho = 1.204  # Luftdichte bei 20°C

    def wheel_demand(self, vehicle, v, a, slope):
        """Calculate the traction demand at the wheels by calculating driving resistances"""
        if v > 0.01:
            F_r = vehicle.c_rolling * vehicle.mass * self.g * np.cos(slope)
        else:
            F_r = 0
        F_slope = vehicle.mass * self.g * np.sin(slope)
        F_i = vehicle.rot_inertia * vehicle.mass * a
        F_d = vehicle.c_w * vehicle.front_area * self.rho / 2 * np.power(v, 2)
        F_trac = F_r + F_slope + F_i + F_d

        self.M_slope.append(F_slope * vehicle.rolling_radius_rear)
        self.M_resist.append(F_r * vehicle.rolling_radius_rear)
        self.M_inertial.append(F_i * vehicle.rolling_radius_rear)
        self.M_drag.append(F_d * vehicle.rolling_radius_rear)

        self.M_trac.append(F_trac * vehicle.rolling_radius_rear)

        self.n_trac.append(60 / (2 * np.pi) * v / vehicle.rolling_radius_rear)
        if self.n_trac[-1] < 0:
            pass
        return F_r, F_d, F_i, F_slope, F_trac

    def torquesplit(self, vehicle, v, a, slope, dt=TAKTRATE):
        corrected = False
        limit_speed = False
        limit_torque = False
        limited = False
        M_EM_unlimited = []

        if self.n_trac[-1] == 0:
            J_opt = 0
            M_EM1_opt, M_EM2_opt, M_EM3_opt, M_EM4_opt = 0, 0, 0, 0
            n_EM1, n_EM2, n_EM3, n_EM4 = 0, 0, 0, 0
            E_EM1, E_EM2, E_EM3, E_EM4, E_el = 0, 0, 0, 0, 0
            P_EM1, P_EM2, P_EM3, P_EM4 = 0, 0, 0, 0
            P_EM1_opt_eta, P_EM2_opt_eta, P_EM3_opt_eta, P_EM4_opt_eta = 0, 0, 0, 0
            P_slope, P_resist, P_inertial, P_drag = 0, 0, 0, 0

            eta_EM12_opt_raw, eta_EM34_opt_raw = 0, 0
            self.M_brake_mech.append(self.M_trac[-1])
            axle_ratio_opt = 0.5
        else:
            axle_ratio = np.linspace(0., 1., self.axle_ratio_reso)
            axle_ratio = np.reshape(axle_ratio, (1, self.axle_ratio_reso))

            n_EM1 = self.n_trac[-1] * vehicle.EM_front_1.gear_ratio
            n_EM2 = self.n_trac[-1] * vehicle.EM_front_2.gear_ratio
            n_EM3 = self.n_trac[-1] * vehicle.EM_rear_1.gear_ratio
            n_EM4 = self.n_trac[-1] * vehicle.EM_rear_2.gear_ratio

            n_EM_mtrx = n_EM1 * np.ones(np.shape(axle_ratio))

            """front axle"""
            M_EM1, M_EM_max_front, M_EM_max_rec_front, M_EM1_diff, M_EM1_penalty, eta_EM12 = vehicle.EM_front_1.calc_EM_Moments(
                n_EM1, self.axle_ratio_reso, axle_ratio, n_EM_mtrx, self.M_trac[-1])
            M_EM2 = M_EM1

            """back axle"""
            M_EM3, M_EM_max_rear, M_EM_max_rec_rear, M_EM3_diff, M_EM3_penalty, eta_EM34 = vehicle.EM_rear_1.calc_EM_Moments(
                n_EM3, self.axle_ratio_reso, (1 - axle_ratio), n_EM_mtrx, self.M_trac[-1])
            M_EM4 = M_EM3

            """Cost function"""
            J_front = n_EM_mtrx * (M_EM1 + M_EM2) * M_EM1_penalty * 1 / eta_EM12
            J_back = n_EM_mtrx * (M_EM3 + M_EM4) * M_EM3_penalty * 1 / eta_EM34
            J = J_front + J_back

            if np.all(np.isnan(J)):
                M_EM1_opt, M_EM2_opt, M_EM3_opt, M_EM4_opt, M_brake_mech, error_speed, M_EM_unlimited12, M_EM_unlimited34 = self.limittorque(
                    vehicle, slope, M_EM12=(M_EM1 + M_EM2), M_EM34=(M_EM3 + M_EM4), n_EM=n_EM1,
                    ratio_reso=self.axle_ratio_reso)
                self.M_brake_mech.append(M_brake_mech)
                axle_ratio_opt = 0.5
                limited = True
                if error_speed:
                    self.M_EM_opt = 0
                    self.n_EM_opt = 0
                    self.E_EM = 100000
                    self.SOC = vehicle.Battery.SOC[-1]
                    corrected = True
                    limit_speed = True
                    return corrected, limit_speed, limit_torque
                elif not error_speed and M_EM1_opt < 0:
                    pass
                else:
                    self.calculate_reduced_a(M_EM1_opt, M_EM3_opt, M_EM_unlimited12, M_EM_unlimited34, vehicle, v, a,
                                             slope)
                    M_EM2_opt = M_EM1_opt
                    M_EM4_opt = M_EM3_opt
                    if self.n_trac[-1] * vehicle.rolling_radius_rear / (60 / (2 * np.pi)) > 100:
                        pass
                    corrected = True
                    limit_torque = True
            else:
                """Search operating point with minimal cost"""
                axle_ratio_opt_index = np.unravel_index(np.nanargmin(J), J.shape)
                axle_ratio_opt = np.nanargmin(J) / (self.axle_ratio_reso - 1)
                M_EM1_opt = M_EM1[axle_ratio_opt_index]
                M_EM2_opt = M_EM2[axle_ratio_opt_index]
                M_EM3_opt = M_EM3[axle_ratio_opt_index]
                M_EM4_opt = M_EM4[axle_ratio_opt_index]
                self.M_brake_mech.append(0)

            eta_EM12_opt_raw = vehicle.EM_front_1.EM['eta_interp_fnc'](n_EM1, M_EM1_opt)[0][0]
            if M_EM1_opt * n_EM1 < 0:
                eta_EM12_opt = 1 / eta_EM12_opt_raw
            else:
                eta_EM12_opt = eta_EM12_opt_raw

            eta_EM34_opt_raw = vehicle.EM_rear_1.EM['eta_interp_fnc'](n_EM3, M_EM3_opt)[0][0]
            if M_EM3_opt * n_EM3 < 0:
                eta_EM34_opt = 1 / eta_EM34_opt_raw
            else:
                eta_EM34_opt = eta_EM34_opt_raw

            M_EM_recup_max = M_EM_max_rec_front
            if M_EM1_opt < M_EM_recup_max:
                M_EM1_opt = M_EM_recup_max
                M_EM2_opt = M_EM_recup_max
                limited = True
            M_EM_recup_max = M_EM_max_rec_rear
            if M_EM3_opt < M_EM_recup_max:
                M_EM3_opt = M_EM_recup_max
                M_EM4_opt = M_EM_recup_max
                limited = True

            if self.M_trac[-1] > 0 and limited:
                M_EM_unlimited_per_motor_front = M_EM_unlimited12 / 2
                M_EM_unlimited_per_motor_rear = M_EM_unlimited34 / 2

                P_EM1 = 2 * np.pi / 60 * n_EM1 * M_EM_unlimited_per_motor_front * 1 / eta_EM12_opt
                P_EM2 = 2 * np.pi / 60 * n_EM2 * M_EM_unlimited_per_motor_front * 1 / eta_EM12_opt
                P_EM3 = 2 * np.pi / 60 * n_EM3 * M_EM_unlimited_per_motor_rear * 1 / eta_EM34_opt
                P_EM4 = 2 * np.pi / 60 * n_EM4 * M_EM_unlimited_per_motor_rear * 1 / eta_EM34_opt
            else:
                P_EM1 = 2 * np.pi / 60 * n_EM1 * M_EM1_opt * 1 / eta_EM12_opt
                P_EM2 = 2 * np.pi / 60 * n_EM2 * M_EM2_opt * 1 / eta_EM12_opt
                P_EM3 = 2 * np.pi / 60 * n_EM3 * M_EM3_opt * 1 / eta_EM34_opt
                P_EM4 = 2 * np.pi / 60 * n_EM4 * M_EM4_opt * 1 / eta_EM34_opt

            P_EM1_opt_eta = 2 * np.pi / 60 * n_EM1 * M_EM1_opt * 1 / 1
            P_EM2_opt_eta = 2 * np.pi / 60 * n_EM2 * M_EM2_opt * 1 / 1
            P_EM3_opt_eta = 2 * np.pi / 60 * n_EM3 * M_EM3_opt * 1 / 1
            P_EM4_opt_eta = 2 * np.pi / 60 * n_EM4 * M_EM4_opt * 1 / 1

            P_slope = 2 * np.pi / 60 * n_EM1 * self.M_slope[-1] * 1 / 1
            P_resist = 2 * np.pi / 60 * n_EM1 * self.M_resist[-1] * 1 / 1
            P_inertial = 2 * np.pi / 60 * n_EM1 * self.M_inertial[-1] * 1 / 1
            P_drag = 2 * np.pi / 60 * n_EM1 * self.M_drag[-1] * 1 / 1

            # Berechnet die elektrische Energie auf Basis der Taktrate
            E_el = (P_EM1 + P_EM2 + P_EM3 + P_EM4) * dt

        vehicle.EM_front_1.M_EM_opt.append(float(M_EM1_opt))
        vehicle.EM_front_2.M_EM_opt.append(float(M_EM2_opt))
        vehicle.EM_front_1.n_EM_opt.append(n_EM1)
        vehicle.EM_front_2.n_EM_opt.append(n_EM2)
        vehicle.EM_front_1.P_EM.append(float(P_EM1))
        vehicle.EM_front_2.P_EM.append(float(P_EM2))
        vehicle.EM_front_1.eta_EM12_opt.append(float(eta_EM12_opt_raw))
        vehicle.EM_front_2.eta_EM12_opt.append(float(eta_EM12_opt_raw))

        vehicle.EM_rear_1.M_EM_opt.append(float(M_EM3_opt))
        vehicle.EM_rear_2.M_EM_opt.append(float(M_EM4_opt))
        vehicle.EM_rear_1.n_EM_opt.append(n_EM3)
        vehicle.EM_rear_2.n_EM_opt.append(n_EM4)
        vehicle.EM_rear_1.P_EM.append(float(P_EM3))
        vehicle.EM_rear_2.P_EM.append(float(P_EM4))
        vehicle.EM_rear_1.eta_EM12_opt.append(float(eta_EM34_opt_raw))
        vehicle.EM_rear_2.eta_EM12_opt.append(float(eta_EM34_opt_raw))

        self.Torque_split_opt.append(axle_ratio_opt)
        self.M_total.append(float(M_EM1_opt + M_EM2_opt + M_EM3_opt + M_EM4_opt))
        self.P_total.append(float(P_EM1 + P_EM2 + P_EM3 + P_EM4))

        self.P_slope.append(P_slope)
        self.P_resist.append(P_resist)
        self.P_inertial.append(P_inertial)
        self.P_drag.append(P_drag)
        self.E_total.append(E_el)
        self.P_total_opt_eta.append(float(P_EM1_opt_eta + P_EM2_opt_eta + P_EM3_opt_eta + P_EM4_opt_eta))

        a_real, a_diff = self.forward_dyn(vehicle, a, slope)

        return corrected, limit_speed, limit_torque

    def limittorque(self, vehicle, slope, M_EM12=[], M_EM34=[], n_EM=[], ratio_reso=[]):
        error_speed = False
        axle_ratio_opt_index = (0, int(ratio_reso / 2))
        if M_EM12[axle_ratio_opt_index] > 0:
            M_EM1_opt = vehicle.EM_front_1.EM['M_max_interp_fnc'](n_EM)[0]
            M_EM2_opt = vehicle.EM_front_2.EM['M_max_interp_fnc'](n_EM)[0]
            M_EM3_opt = vehicle.EM_rear_1.EM['M_max_interp_fnc'](n_EM)[0]
            M_EM4_opt = vehicle.EM_rear_2.EM['M_max_interp_fnc'](n_EM)[0]
        else:
            M_EM1_opt = vehicle.EM_front_1.EM['M_max_rec_interp_fnc'](n_EM)[0]
            M_EM2_opt = vehicle.EM_front_2.EM['M_max_rec_interp_fnc'](n_EM)[0]
            M_EM3_opt = vehicle.EM_rear_1.EM['M_max_rec_interp_fnc'](n_EM)[0]
            M_EM4_opt = vehicle.EM_rear_2.EM['M_max_rec_interp_fnc'](n_EM)[0]

        M_EM_unlimited12 = M_EM12[axle_ratio_opt_index]
        M_EM_unlimited34 = M_EM34[axle_ratio_opt_index]
        if M_EM12[axle_ratio_opt_index] < 0:
            M_brake_mech = (M_EM_unlimited12 - M_EM1_opt) \
                           + (M_EM_unlimited12 - M_EM2_opt) \
                           + ((M_EM_unlimited34 - M_EM3_opt) + (
                        M_EM_unlimited34 - M_EM4_opt)) * vehicle.EM_rear_1.gear_ratio
        else:
            M_brake_mech = 0

        if n_EM > np.amax(vehicle.EM_front_1.EM['grid_speed']):
            error_speed = True

        return M_EM1_opt, M_EM2_opt, M_EM3_opt, M_EM4_opt, M_brake_mech, error_speed, M_EM_unlimited12, M_EM_unlimited34

    def calculate_reduced_a(self, M_EM1_opt, M_EM3_opt, M_EM_unlimited12, M_EM_unlimited34, vehicle, v, a, slope):
        M_EM1_Dif = M_EM_unlimited12 - M_EM1_opt * 2
        M_EM3_Dif = M_EM_unlimited34 - M_EM3_opt * 2

        if M_EM1_Dif + M_EM3_Dif <= 0:
            if M_EM1_Dif > 0:
                M_EM1_opt = M_EM1_opt
                M_EM3_opt = (M_EM_unlimited34 + M_EM1_Dif) / 2

            if M_EM3_Dif > 0:
                M_EM3_opt = M_EM3_opt
                M_EM1_opt = (M_EM_unlimited12 + M_EM3_Dif) / 2
        else:
            M_Max = M_EM1_opt * 2 + M_EM3_opt * 2
            F_Max = M_Max / vehicle.rolling_radius_rear

            if v > 0.01:
                F_r = vehicle.c_rolling * vehicle.mass * self.g * np.cos(slope)
            else:
                F_r = 0

            F_slope = vehicle.mass * self.g * np.sin(slope)
            F_d = vehicle.c_w * vehicle.front_area * self.rho / 2 * np.power(v, 2)
            F_i_Max = F_Max - F_r - F_slope - F_d
            a_set_max = F_i_Max / (vehicle.rot_inertia * vehicle.mass)
            a = a_set_max

    def forward_dyn(self, vehicle, a, slope):
        try:
            if self.n_trac[-1] == 0:
                M_trac = self.M_trac[-1]
            else:
                M_trac = vehicle.EM_front_1.M_EM_opt[-1] + vehicle.EM_front_2.M_EM_opt[-1] + vehicle.EM_rear_1.M_EM_opt[
                    -1] + vehicle.EM_rear_2.M_EM_opt[-1] + (self.M_brake_mech[-1] * 1 / vehicle.EM_rear_1.gear_ratio)

            v = self.n_trac[-1] * vehicle.rolling_radius_rear * 2 * np.pi / 60
            if v > 0.01:
                F_r = vehicle.c_rolling * vehicle.mass * self.g * np.cos(slope)
            else:
                F_r = 0

            a_forward = (-1 / (vehicle.rot_inertia * vehicle.mass)) * ((F_r + vehicle.mass * self.g * np.sin(
                slope) + vehicle.c_w * vehicle.front_area * self.rho / 2 * np.power(v,
                                                                                    2) - M_trac / vehicle.rolling_radius_rear))
            a_diff = a - a_forward
            return a_forward, a_diff
        except Exception as e:
            return {
                "error": str(e), "a": a, "slope": slope, "n_trac": self.n_trac[-1] if hasattr(self, "n_trac") else None,
                "M_trac": self.M_trac[-1] if hasattr(self, "M_trac") else None,
                "M_brake_mech": self.M_brake_mech[-1] if hasattr(self, "M_brake_mech") else None,
                "v": v if "v" in locals() else None, "F_r": F_r if "F_r" in locals() else None,
            }

    def calc_E_El_bat(self, vehicle, dt=TAKTRATE):
        delta_t = dt
        E_el_mot = self.P_total[-1] * delta_t
        self.E_el_mot.append(E_el_mot)

        eta_battery = vehicle.Battery.calculate_eta(self.M_trac[-1], self.n_trac[-1])
        P_el_bat = self.P_total[-1] * eta_battery
        E_el_bat = E_el_mot * eta_battery
        self.P_el_bat.append(P_el_bat)
        self.E_el_bat.append(E_el_bat)

        return E_el_bat

    def calculations_for_results(self, vehicle):
        if self.M_trac[-1] >= 0:
            M_rec = 0
        else:
            M_rec = (2 * vehicle.EM_rear_1.M_EM_opt[-1] + 2 * vehicle.EM_front_1.M_EM_opt[-1])

        self.M_rec.append(M_rec)

    def calc_losses(self, vehicle, M_brake_mech, v):
        P_Verlust_Batterie = abs(self.P_el_bat[-1] - self.P_total[-1])
        P_Verlust_Bremse = M_brake_mech * v
        P_Verlust_Getriebe = abs((self.M_trac[-1] * self.n_trac[-1] * 2 * np.pi / 60) - (
                2 * vehicle.EM_front_1.M_EM_opt[-1] * vehicle.EM_front_1.n_EM_opt[-1] * 2 * np.pi / 60 +
                2 * vehicle.EM_rear_1.M_EM_opt[-1] * vehicle.EM_rear_1.n_EM_opt[
                    -1] * 2 * np.pi / 60)) - P_Verlust_Bremse
        P_Verlust_Motor = abs(self.P_total[-1] - (
                2 * vehicle.EM_front_1.M_EM_opt[-1] * vehicle.EM_front_1.n_EM_opt[-1] * 2 * np.pi / 60 +
                2 * vehicle.EM_rear_1.M_EM_opt[-1] * vehicle.EM_rear_1.n_EM_opt[-1] * 2 * np.pi / 60))
        return P_Verlust_Getriebe, P_Verlust_Motor, P_Verlust_Batterie, P_Verlust_Bremse

    def operating_strategy(self, vehicle, v, a, slope, dt=TAKTRATE):
        F_r, F_d, F_i, F_slope, F_trac = self.wheel_demand(vehicle, v, a, slope)

        corrected, limit_speed, limit_torque = self.torquesplit(vehicle, v, a, slope, dt=dt)

        E_el_bat = self.calc_E_El_bat(vehicle, dt=dt)
        M_rec = self.calculations_for_results(vehicle)

        M_trac = self.M_trac[-1]
        n_trac = self.n_trac[-1]
        n_EM_front = vehicle.EM_front_1.n_EM_opt[-1]
        n_EM_rear = vehicle.EM_rear_1.n_EM_opt[-1]
        M_brake_mech = abs(
            self.M_trac[-1] - (self.M_rec[-1] * (1 / vehicle.EM_rear_1.gear_eta) * vehicle.EM_rear_1.gear_ratio)) \
            if (self.M_trac[-1] - (
                    self.M_rec[-1] * (1 / vehicle.EM_rear_1.gear_eta) * vehicle.EM_rear_1.gear_ratio)) < 0 else 0
        M_EM_front = vehicle.EM_front_1.M_EM_opt[-1]
        M_EM_rear = vehicle.EM_rear_1.M_EM_opt[-1]
        eta_EM_front = vehicle.EM_front_1.eta_EM12_opt[-1]
        eta_EM_rear = vehicle.EM_rear_1.eta_EM12_opt[-1]
        P_el_mot = self.P_total[-1]
        E_el_mot = self.E_el_mot[-1]
        P_el_bat = self.P_el_bat[-1]

        distance = v * dt
        self.distance.append(distance)

        P_Verlust_Getriebe, P_Verlust_Motor, P_Verlust_Batterie, P_Verlust_Bremse = self.calc_losses(vehicle,
                                                                                                     M_brake_mech, v)

        M_trac_1 = None;
        M_trac_2 = None;
        n_EM = None;
        n_EM_1 = None;
        n_EM_2 = None;
        M_EM = None
        eta_EM = None;
        eta_EM_1 = None;
        eta_EM_2 = None;
        optimal_gear = None;
        M_EM_1_checked = None;
        M_EM_2_checked = None

        results = {
            'M_trac': self.M_trac[-1],
            'n_trac': self.n_trac[-1],
            'n_EM_front': vehicle.EM_front_1.n_EM_opt[-1],
            'n_EM_rear': vehicle.EM_rear_1.n_EM_opt[-1],
            'M_rec': self.M_rec[-1],
            'M_brake_mech': self.M_trac[-1] - (
                        self.M_rec[-1] * (1 / vehicle.EM_rear_1.gear_eta) * vehicle.EM_rear_1.gear_ratio),
            'M_EM_front': vehicle.EM_front_1.M_EM_opt[-1],
            'M_EM_rear': vehicle.EM_rear_1.M_EM_opt[-1],
            'eta_EM_front': eta_EM_front,
            'eta_EM_rear': eta_EM_rear,
            'P_el_mot': self.P_total[-1],
            'E_el_mot': self.E_el_mot[-1],
            'E_el_bat': self.E_el_bat[-1],
            'P_el_bat': self.P_el_bat[-1],
            'distance': distance,
            'vehicle': self.ID,
            'corrected': corrected,
            'limit_speed': limit_speed,
            'limit_torque': limit_torque
        }

        return results, M_trac, M_trac_1, M_trac_2, n_trac, n_EM, n_EM_front, n_EM_rear, n_EM_1, n_EM_2, M_rec, M_brake_mech, M_EM, M_EM_front, M_EM_rear, M_EM_1_checked, M_EM_2_checked, eta_EM, eta_EM_front, eta_EM_rear, eta_EM_1, eta_EM_2, optimal_gear, P_el_mot, E_el_mot, E_el_bat, P_el_bat, distance, P_Verlust_Getriebe, P_Verlust_Motor, P_Verlust_Batterie, P_Verlust_Bremse, F_r, F_d, F_i, F_slope, F_trac