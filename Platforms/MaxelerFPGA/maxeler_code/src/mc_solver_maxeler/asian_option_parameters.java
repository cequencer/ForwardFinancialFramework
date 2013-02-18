package mc_solver_maxeler;

import com.maxeler.maxcompiler.v1.kernelcompiler.types.base.HWVar;

public class asian_option_parameters extends european_option_parameters 
	protected final HWVar points;

	public asian_option_parameters(MC_Solver_Maxeler_Base_Kernel k,HWVar time_period,HWVar call,HWVar strike_price,HWVar observation_points){
		super(k,time_period,call,strike_price);

		this.points = observation_points;
	}
}
