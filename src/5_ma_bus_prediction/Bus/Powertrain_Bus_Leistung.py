import scipy
from scipy import interpolate
import numpy as np

class Powertrain_Bus:

    def __init__(self, EM_Map_file, gear_eta, gear_ratio):
        self.M_EM_opt = []
        self.n_EM_opt = []
        self.P_EM = []
        self.eta_EM12_opt = []
        self.gear_ratio = gear_ratio
        self.gear_eta = gear_eta
        self.EM = scipy.io.loadmat(EM_Map_file)  # EM.mat = DE-REX EM -- loads the matlab struct as a python dictionary with numpy array entries

        self.EM['name'] = str(int(self.EM['power'])) + 'kw'
        self.EM['M_max_interp_fnc'] = interpolate.interp1d(
            np.reshape(self.EM['grid_speed'], (-1,)),
            self.EM['max_torque'],
            bounds_error=False
        )
        self.EM['eta_interp_fnc'] = interpolate.RectBivariateSpline(
            np.reshape(self.EM['grid_speed'], (-1,)),
            np.reshape(self.EM['grid_torque'], (-1,)),
            self.EM['efficiency'],
            kx=1, ky=1
        )
        self.EM['M_max_rec_interp_fnc'] = interpolate.interp1d(
            np.reshape(self.EM['grid_speed'], (-1,)),
            self.EM['max_torque_rec'],
            bounds_error=False
        )
        self.EM['eta_max'] = float(np.max(self.EM['efficiency']))
        self.EM['eta_min'] = float(np.min(self.EM['efficiency']))

    def calc_EM_Moments(self, n_EM, axle_ratio_reso, axle_ratio, n_EM_mtrx, M_trac):
        # Berechne zunächst das angefragte Moment:
        if M_trac > 0:
            # Vortriebsfall: Effizienz wird invers (1/gear_eta) berücksichtigt
            M_EM = 0.5 * M_trac * axle_ratio * (1 / self.gear_ratio) * (1 / self.gear_eta)
        else:
            # Rekuperationsfall: Hier wird gear_eta direkt multipliziert
            M_EM = 0.5 * M_trac * axle_ratio * (1 / self.gear_ratio) * self.gear_eta

        # Ermitteln Sie die zulässigen Maximalwerte:
        M_EM_max = self.EM['M_max_interp_fnc'](n_EM)
        M_EM_max_rec = self.EM['M_max_rec_interp_fnc'](n_EM)

        # Im Rekuperationsfall (M_trac <= 0) wird das Moment in den zulässigen Bereich begrenzt.
        # Dabei nehmen wir an, dass M_EM_max_rec einen negativen Wert (z.B. -100 Nm) darstellt.
        # np.clip sorgt dafür, dass M_EM nicht kleiner als M_EM_max_rec wird und nicht größer als 0 (kein positiver Rekuperationswert) ist.
        if M_trac <= 0:
            M_EM = np.clip(M_EM, M_EM_max_rec, 0)

        # Berechne den Unterschied zum maximalen Vortriebs-Moment (wird für die Penalty herangezogen)
        M_EM_diff = M_EM - M_EM_max * np.ones(np.shape(M_EM))
        M_EM_penalty = np.ones(M_EM_diff.shape)
        M_EM_penalty[M_EM_diff > 0] = np.nan

        # Interpolation der Effizienz anhand des (nun begrenzten) Momentwerts
        eta_EM = self.EM['eta_interp_fnc'](n_EM_mtrx, M_EM, grid=False)
        eta_EM = np.reshape(eta_EM, (1, axle_ratio_reso))
        eta_EM[n_EM_mtrx > np.amax(self.EM['grid_speed'])] = np.nan
        eta_EM[abs(M_EM) > np.amax(self.EM['grid_torque'])] = np.nan
        # Bei Rekuperation (M_EM * n_EM_mtrx < 0) wird der Wirkungsgrad invertiert
        eta_EM[M_EM * n_EM_mtrx < 0] = 1 / eta_EM[M_EM * n_EM_mtrx < 0]

        return M_EM, M_EM_max, M_EM_max_rec, M_EM_diff, M_EM_penalty, eta_EM
