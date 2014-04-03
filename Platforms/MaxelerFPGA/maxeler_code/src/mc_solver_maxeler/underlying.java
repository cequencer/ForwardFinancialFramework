package mc_solver_maxeler;

import com.maxeler.maxcompiler.v2.kernelcompiler.Kernel;
import com.maxeler.maxcompiler.v2.kernelcompiler.KernelLib;
import com.maxeler.maxcompiler.v2.kernelcompiler.types.base.DFEVar;

public class underlying extends KernelLib {

	String name = "underlying";

	protected Kernel kernel;
	protected DFEVar point;
	protected DFEVar path;
	protected DFEVar delay;

	protected underlying_parameters parameters;

	protected DFEVar gamma;
	protected DFEVar carried_gamma;
	protected DFEVar new_gamma;
	protected DFEVar time;
	protected DFEVar carried_time;
	protected DFEVar new_time;

	//protected DFEVar temp_price;
	//protected DFEVar delta_time;

	public underlying(MC_Solver_Maxeler_Base_Kernel k,DFEVar pp,DFEVar p,DFEVar d,underlying_parameters up){
		super(k);
		this.point = pp;
		this.path = p;
		this.delay = d;
		//this.temp_price = tp;
		//this.delta_time = dt;

		this.parameters = up;
		this.kernel = k;
		//this.path_init();
		//this.path();


		//this.gamma = this.kernel.constant.var(doubleType,0.0);//doubleType.newInstance(this.kern);
		//this.time = this.kernel.constant.var(doubleType,0.0);//doubleType.newInstance(this.kern);


	}

	public DFEVar getCurrentPrice(){
		return this.parameters.current_price;
	}

	public void path_init(){
		this.carried_gamma = ((MC_Solver_Maxeler_Base_Kernel)this.kernel).inputDoubleType.newInstance(this.kernel);
		this.carried_time = ((MC_Solver_Maxeler_Base_Kernel)this.kernel).inputDoubleType.newInstance(this.kernel);

		this.gamma = this.point.eq(0)&this.delay.eq(0) ? 0.0 : carried_gamma;
		this.time = this.point.eq(0)&this.delay.eq(0) ? 0.0 : carried_time;
	}

	public void path(DFEVar delta_time){
		this.new_gamma = this.gamma + delta_time*this.parameters.rfir;
		this.new_time = this.time + delta_time;
		//this.temp_price = this.parameters.current_price*(KernelMath.exp(this.new_gamma.cast(this.kernel.expType)));
	}

	public void connect_path(boolean pipeline, DFEVar path_gamma,DFEVar path_time){
		//boolean pipeline, DFEVar path_gamma,DFEVar path_time
		if(pipeline){
			this.carried_gamma <== path_gamma;
			this.carried_time <== path_time;
		}
		else{
			this.carried_gamma <== this.stream.offset(path_gamma,-((MC_Solver_Maxeler_Base_Kernel)this.kernel).delay);
			this.carried_time <== this.stream.offset(path_time,-((MC_Solver_Maxeler_Base_Kernel)this.kernel).delay);
		}
	}

	public underlying_parameters getParameters(){
		return this.parameters;
	}

	/*public DFEVar path(DFEVar delta_time){
		//this.gamma = this.carried_gamma + this.rfir*delta_time;// + this.rfir*delta_time;
		this.time = this.carried_time + delta_time;

		return this.new_gamma;
	}*/

	/*public DFEVar getGamma(){
		return this.gamma;
	}



	public DFEVar getTime(){
		return this.time;
	}

	public void setGamma(DFEVar g){
		this.gamma = g;
	}

	public DFEVar getRfir(){
		return this.rfir;
	}*/

}
