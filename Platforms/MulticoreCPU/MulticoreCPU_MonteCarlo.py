'''
Created on 30 October 2012

'''
import os,time,subprocess,sys,time,math,platform,random
from ForwardFinancialFramework.Solvers.MonteCarlo import MonteCarlo

class MulticoreCPU_MonteCarlo(MonteCarlo.MonteCarlo):
  def __init__(self,derivative,paths,platform,reduce_underlyings=True,random_number_generator="taus_ziggurat",floating_point_format="double",default_points=4096):
    MonteCarlo.MonteCarlo.__init__(self,derivative,paths,platform,reduce_underlyings)
    self.solver_metadata["threads"] = self.platform.threads #Number of threads set by the platform
    self.solver_metadata["default_points"] = default_points
    self.solver_metadata["rng_seed"] = 0
    
    self.utility_libraries = ["math.h","pthread.h","stdint.h","stdlib.h","stdio.h","time.h","sys/resource.h","unistd.h","string.h"]
    if("darwin" in sys.platform): self.utility_libraries.append("mach/mach_time.h")
    self.activity_thread_name = "multicore_montecarlo_activity_thread"
    
    self.floating_point_format = floating_point_format
    
    self.header_string = "//%s.c Generated by Monte Carlo MulticoreCPU Solver"%self.output_file_name
    
    self.random_number_generator = random_number_generator
    
  
  #def __setstate__(self,state):
     #MonteCarlo.MonteCarlo.__setstate__(self,state)
  
  def generate(self,name_extension=".c",override=True,verbose=False,debug=False):
    #os.chdir("..")
    #os.chdir(self.platform.platform_directory())
    
    if(override or not os.path.exists("%s/%s%s"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name,name_extension))):
        #os.chdir(self.platform.root_directory())
        #os.chdir("bin")
      
        code_string = []
        code_string.extend(self.generate_identifier())
        code_string.extend(self.generate_libraries())
        code_string.extend(self.generate_variable_declaration())
        code_string.extend(self.generate_activity_thread())
        code_string.extend(self.generate_main_thread())
        
        #Actually writing to the file
        self.generate_source(code_string,name_extension,verbose,debug)
        
    #os.chdir(self.platform.root_directory())
    #os.chdir("bin")
  
  def generate_identifier(self):
    output_list = []
    output_list.append(self.header_string)
    #output_list.append("#define %s 1"%self.platform.name.upper())
    output_list.append("#define MULTICORE_CPU")
    output_list.append("#define FP_t %s"%self.floating_point_format)
    output_list.append("#define native_sqrt sqrt")
    output_list.append("#define native_exp exp")
    
    return output_list
    
  def generate_libraries(self):
    #Checking that the platform source code for the derivatives and underlyings required are present
    #os.chdir("..")
    #os.chdir(self.platform.platform_directory())
    
    underlying_libraries = []
    for u in self.underlying:
      if(not(os.path.exists("%s/%s.c"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),u.name))) or not(os.path.exists("%s/%s.h"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),u.name)))): raise IOError, ("missing the source code for the underlying - %s.c or %s.h" % (u.name,u.name))
      else: underlying_libraries.append("%s.h"%u.name)
        
    derivative_libraries = []    
    for d in self.derivative:
      if(not(os.path.exists("%s/%s.c"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),d.name))) or not(os.path.exists("%s/%s.h"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),d.name)))): raise IOError, ("missing the source code for the derivative - %s.c or %s.h" %  (d.name,d.name))
      else: derivative_libraries.append("%s.h"%d.name)
      
    #os.chdir(self.platform.root_directory())
    #os.chdir("bin")
    
    output_list = ["//Libraries"]
    for u in self.utility_libraries: output_list.append("#include \"%s\";"%u)
    for u in underlying_libraries: output_list.append("#include \"%s\";"%u)
    for d in derivative_libraries: output_list.append("#include \"%s\";"%d)
  
    return output_list
  
  def generate_variable_declaration(self):
    #Generate Intermediate and Communication Variables
      output_list = []
      output_list.append("//*Intermediate and Communication Variables*")
      
      for d in self.derivative:
          index = self.derivative.index(d)
          for u in d.underlying:
              u_index = self.underlying.index(u)
              output_list.append("FP_t discount_%d_%d;"%(index,u_index))
              
          output_list.append("FP_t option_price_%d;"%index)
          output_list.append("FP_t option_price_%d_confidence_interval;"%index)
          
      index = 0
      for u_a in self.underlying_attributes:
          for a in u_a: output_list.append("static FP_t %s_%d_%s;"%(self.underlying[index].name,index,a)) #execution code must mirror this ordering
          index += 1
      
      index = 0
      for o_a in self.derivative_attributes:
          for o in o_a: output_list.append("static FP_t %s_%d_%s;"%(self.derivative[index].name,index,o)) #execution code must mirror this ordering
          index += 1
          
      for k in sorted(self.solver_metadata): output_list.append("static int %s;"%k) 
          
      output_list.append("int thread_paths,i,j;")
      
      output_list.append("struct thread_data{")
      output_list.append("int thread_paths;")
      output_list.append("unsigned int thread_rng_seed;")
      output_list.append("double *thread_result;")
      output_list.append("double *thread_result_sqrd;")
      output_list.append("};")
      
      #Performance Monitoring Variables
      output_list.append("//*Performance Monitoring Variables*")
      #output_list.append("FP_t system_time,user_time,cpu_time,wall_time;")
      output_list.append("FP_t setup_time,activity_time;")
      if("darwin" not in sys.platform):
        output_list.append("struct timespec start, setup_end, end;")
      else:
        output_list.append("uint64_t start, setup_end, end;")
      output_list.append("int ret,ret_2;")
      #output_list.append("struct rusage usage,usage_2;")
      
      return output_list
  
  def generate_main_thread(self):
    output_list = []
	
    #Declare Main Function
    output_list.append("//*Main Function*")
    output_list.append("int main(int argc,char* argv[]){")
    #Starting timers
    output_list.append("//**Starting Timers**")
    #output_list.append("int who = RUSAGE_SELF;")
    #output_list.append("gettimeofday(&start,NULL);")
    if("darwin" not in sys.platform): 
      output_list.append("clock_gettime(CLOCK_MONOTONIC,&start);")
    else:
      output_list.append("start = mach_absolute_time();")
    #output_list.append("ret=getrusage(who,&usage);")
    ##Commented out diagnostic tool
    #output_file.write("/*for(i=0;i<argc;i++){//For diagnostic Purposes\nprintf(\"%s \",argv[i]);\n}*/\n")
    
    ##Convert command line arguments to static variables
    output_list.append("//**Unpacking Command Line Variables**")
    temp = 1
    output_list.append("//***Solver Metadata***")
    for k in self.solver_metadata.keys(): 
        output_list.append("%s = atoi(argv[%d]);"%(k,temp))
        temp += 1
    
    conversion_function = "strtod"
    if(self.floating_point_format=="float"): conversion_function = "strtof"
    
    output_list.append("//***Underlying Attributes***")
    for i,u_a in enumerate(self.underlying_attributes):
        for a in u_a:
            output_list.append("%s_%d_%s = %s(argv[%d],NULL);"%(self.underlying[i].name,i,a,conversion_function,temp))
            temp += 1
        i += 1
    
    output_list.append("//***Derivative Attributes***")
    for i,o_a in enumerate(self.derivative_attributes):
        for a in o_a:
            output_list.append("%s_%d_%s = %s(argv[%d],NULL);"%(self.derivative[i].name,i,a,conversion_function,temp))
            temp += 1
        i += 1
    
    ##Calculate Discount Factor
    output_list.append("//**Calculating Discount Factor**")
    
    for d in self.derivative:
        index = self.derivative.index(d)
        for u in d.underlying:
            u_index = self.underlying.index(u)
            output_list.append("discount_%d_%d = exp(-%s_%d_rfir*%s_%d_time_period);"%(index,u_index,u.name,u_index,d.name,index))
            
    
    ##Create Thread Support Structure
    output_list.append("//**Creating Thread Variables**")
    output_list.append("thread_paths = paths/threads;")
    output_list.append("pthread_t pthreads[threads];")
    #output_list.append("FP_t thread_results[threads][%d];"%len(self.derivative))
    output_list.append("struct thread_data temp_data[threads];")
    output_list.append("for(i=0;i<threads;i++){")
    output_list.append("temp_data[i].thread_result=(FP_t*)malloc(%d*sizeof(FP_t));"%len(self.derivative))
    output_list.append("temp_data[i].thread_result_sqrd=(FP_t*)malloc(%d*sizeof(FP_t));"%len(self.derivative))
    output_list.append("}")
    
    output_list.append("pthread_attr_t attr;")
    output_list.append("pthread_attr_init(&attr);")
    output_list.append("pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_JOINABLE);")
    
    ##Pack up data and pass to threads
    output_list.append("//**Packing up data and passing to threads**")
    output_list.append("int i;");
    output_list.append("for(i=0;i<threads;i++){ //Generating Threads");
    output_list.append("temp_data[i].thread_paths = thread_paths;")
    output_list.append("temp_data[i].thread_rng_seed = rng_seed + i*thread_paths*%d;"%len(self.underlying))
    output_list.append("if(i==(threads-1)){ //If final thread, allocating any remaining paths to it (i.e. PATHS%THREADS!=0)")
    output_list.append("temp_data[i].thread_paths += paths%threads;")
    output_list.append("}")
    #output_list.append("temp_data[i].thread_result = thread_results[i];")
    output_list.append("pthread_create(&pthreads[i],&attr,%s,&temp_data[i]);"%self.activity_thread_name)
    output_list.append("}")
    
    #This is the end of the setup
    if("darwin" not in sys.platform): 
      output_list.append("clock_gettime(CLOCK_MONOTONIC,&setup_end);")
    else:
      output_list.append("setup_end = mach_absolute_time();")
      
    ##Join Threads, aggregate results
    output_list.append("//**Waiting for threads to join**")
    output_list.append("void *status;")
    for d in self.derivative: 
      output_list.append("option_price_%d = 0;"%self.derivative.index(d))
      output_list.append("option_price_%d_confidence_interval = 0;"%self.derivative.index(d))
    output_list.append("for(i=0;i<threads;i++){ //Waiting for Threads");
    output_list.append("pthread_join(pthreads[i],&status);");
    
    for d in self.derivative:
        index = self.derivative.index(d)
        for u in d.underlying:
            u_index = self.underlying.index(u)
            output_list.append("option_price_%d += temp_data[i].thread_result[%d];"%(index,index));
            output_list.append("option_price_%d_confidence_interval += temp_data[i].thread_result_sqrd[%d]; //accumulating variances for calculating the confidence interval"%(index,index));
    
    output_list.append("}")
    
    #output_list.append("FP_t temp_sample_std_dev_%d = pow((temp_value_sqrd_%d/temp_data->thread_paths-pow(temp_total_%d/temp_data->thread_paths,2))/(temp_data->thread_paths-1),0.5);"%(index,index,index)) 
    
    ##Calculate final value and return value
    output_list.append("//**Calculating Final Option Value and Return**")
    for index,d in enumerate(self.derivative):
        output_list.append("option_price_%d = option_price_%d/paths;//Calculate final value and return value as well as timing"%(index,index))
        #output_list.append("option_price_%d_confidence_interval = 1.96*pow((option_price_%d_confidence_interval-paths*pow(option_price_%d,2)),0.5)/paths; //Calculate final confidence interval" % (index,index,index))
        for u in d.underlying: 
	  output_list.append("option_price_%d = option_price_%d*discount_%d_%d;"%(index,index,index,self.underlying.index(u)))
	  #output_list.append("option_price_%d_confidence_interval = option_price_%d_confidence_interval*discount_%d_%d;" % (index,index,index,self.underlying.index(u)))
	  output_list.append("option_price_%d_confidence_interval = option_price_%d_confidence_interval*pow(discount_%d_%d,2);"%(index,index,index,self.underlying.index(u)))
        
        output_list.append("option_price_%d_confidence_interval = 1.96*pow((option_price_%d_confidence_interval-paths*pow(option_price_%d,2)),0.5)/paths; //Calculate final confidence interval" % (index,index,index))
        output_list.append("printf(\"\%f\\n\"")
        output_list.append(",option_price_%d);"%index)
        output_list.append("printf(\"\%f\\n\"")
        output_list.append(",option_price_%d_confidence_interval);"%index)
    
    ##Return Performance evaluation
    output_list.append("//**Performance Monitoring Calculation and Return**")
    #output_list.append("gettimeofday(&end,NULL);")
    if("darwin" not in sys.platform): 
      output_list.append("clock_gettime(CLOCK_MONOTONIC,&end);")
    else:
      output_list.append("end = mach_absolute_time();")
    #output_list.append("ret_2=getrusage(who,&usage_2);")
    
    #output_list.append("user_time = usage_2.ru_utime.tv_sec*1000000+usage_2.ru_utime.tv_usec-(usage.ru_utime.tv_sec*1000000+usage.ru_utime.tv_usec);")
    #output_list.append("system_time = usage_2.ru_stime.tv_sec*1000000+usage_2.ru_stime.tv_usec-(usage.ru_stime.tv_sec*1000000+usage.ru_stime.tv_usec);")
    #output_list.append("cpu_time = (user_time + system_time);")
    if("darwin" not in sys.platform):
      output_list.append("setup_time = 1000000*(setup_end.tv_sec-start.tv_sec)+(setup_end.tv_nsec-start.tv_nsec)/1000;")
      output_list.append("activity_time = 1000000*(end.tv_sec-setup_end.tv_sec)+(end.tv_nsec-setup_end.tv_nsec)/1000;")
    else:
      output_list.append("setup_time = (setup_end-start)/1000;")
      output_list.append("activity_time = (end-setup_end)/1000;")
    
    output_list.append("printf(\"\%f\\n\",setup_time);")
    output_list.append("printf(\"\%f\\n\",activity_time);")
    #output_list.append("printf(\"\%d\\n\",(MemoryUsed()));")
    output_list.append("}")
    
    return output_list
  
  def generate_activity_thread_unpacking(self):
    output_list = []
    #Generate Path Loop Function
    output_list = []
    output_list.append("//*MC Multicore Activity Thread Function*")
    output_list.append("void * %s(void* thread_arg){"%self.activity_thread_name)
    
    ##Declare Loop Data Structures
    output_list.append("//**Loop Data Structures**")
    output_list.append("unsigned int thread_paths = ((struct thread_data*) thread_arg)->thread_paths;")
    output_list.append("unsigned int rng_seed = ((struct thread_data*) thread_arg)->thread_rng_seed;")
    
    for u in self.underlying:
        index = self.underlying.index(u)
        output_list.append("%s_attributes u_a_%d;" % (u.name,index))
        output_list.append("%s_variables u_v_%d;" % (u.name,index))
    
    for d in self.derivative:
        index = self.derivative.index(d)
        output_list.append("%s_attributes o_a_%d;" % (d.name,index))
        output_list.append("%s_variables o_v_%d;" % (d.name,index))
    
    
    output_list.append("//**Initialising Attributes*")
    
    ##Calling Init Functions
    for u_index,u in enumerate(self.underlying):
        temp = ("%s_underlying_init("%u.name)
        for u_a in self.underlying_attributes[u_index][:-1]: temp=("%s%s_%d_%s,"%(temp,u.name,u_index,u_a))
        temp=("%s%s_%d_%s,&u_a_%d);"%(temp,u.name,u_index,self.underlying_attributes[u_index][-1],u_index))
        output_list.append(temp)
    
    for index,d in enumerate(self.derivative):
        
        temp = ("%s_derivative_init("%d.name)
        for o_a in self.derivative_attributes[index][:-1]: temp=("%s%s_%d_%s,"%(temp,d.name,index,o_a))
        temp=("%s%s_%d_%s,&o_a_%d);"%(temp,d.name,index,self.derivative_attributes[index][-1],index))
        output_list.append(temp)
        
        if("points" not in self.derivative_attributes[index]): output_list.append("o_v_%d.delta_time = o_a_%d.time_period/default_points;"%(index,index))
    
    return output_list
  
  def generate_underlying_derivative_path_initialisations(self,linking_variables=True):
    output_list = []
    
    output_list.append("//***Underlying and Derivative Path Initiation***")
    for index,u in enumerate(self.underlying): output_list.append("%s_underlying_path_init(&u_v_%d,&u_a_%d);" % (u.name,index,index))
    
    for index,d in enumerate(self.derivative):
        output_list.append("%s_derivative_path_init(&o_v_%d,&o_a_%d);" % (d.name,index,index))
        
        if(linking_variables):
	  for u_index,u in enumerate(d.underlying):
	      output_list.append("next_time_%d_%d = 0;"%(index,u_index))
	      output_list.append("price_%d_%d = u_a_%d.current_price*exp(u_v_%d.gamma);"%(index,u_index,u_index,u_index))
            
    return output_list
  
  def generate_activity_thread(self):
    output_list = self.generate_activity_thread_unpacking()
    
    ##Thread calculation loop variables
    output_list.append("//**Thread Calculation Loop Variables**")
    
    for r in range(len(self.derivative)):
        output_list.append("FP_t temp_total_%d=0;"%r)
    
    temp="FP_t dummy_2"
    for d in self.derivative:
        index = self.derivative.index(d)
        for u in d.underlying:
            u_index = self.underlying.index(u)
            temp=("%s,price_%d_%d,next_time_%d_%d"%(temp,index,u_index,index,u_index))
            
    for u in self.underlying:
        u_index = self.underlying.index(u)
        temp=("%s,very_next_time_%d"%(temp,u_index))
            
    temp = "%s;"%temp
    output_list.append(temp)
    
    output_list.append("int l,k,done;")
    
    for d in self.derivative:
      index = self.derivative.index(d)
      output_list.append("FP_t temp_total_sqrd_%d=0;"%(index))
      #if(index<(len(self.derivative)-1)): output_list[-1] = ("%stemp_value_sqrd_%d,"%(output_list[-1],index))
      #elif(index==(len(self.derivative)-1)): output_list[-1] = ("%stemp_value_sqrd_%d;"%(output_list[-1],index))
      
    output_list.append("//**Thread Random Number Generator Seeding**")
    for index,u in enumerate(self.underlying):
	if("heston" in u.name or "black_scholes" in u.name):
	  output_list.append("ctrng_seed(1000,rng_seed*thread_paths*%d,&(u_v_%d.rng_state));"%(index+1,index))
    
    output_list.append("//**Thread Path Simulations**")
    output_list.append("for(l=0;l<thread_paths;l++){")
    output_list.extend(self.generate_underlying_derivative_path_initialisations(True))
    
    
    output_list.append("done=1;")
    output_list.append("while(done){")
    output_list.append("//***Derivative Path Function Calls***")
    for index,d in enumerate(self.derivative): #calling the derivative path function
        output_list.append("if(")
        for u in d.underlying:
            u_index = self.underlying.index(u)
            output_list.append("(next_time_%d_%d==u_v_%d.time) && (u_v_%d.time<=o_a_%d.time_period) &&"%(index,u_index,u_index,u_index,index))
        output_list.append(" 1){")
        
        for u in d.underlying:
            u_index = self.underlying.index(u)
            output_list.append("price_%d_%d = u_a_%d.current_price*exp(u_v_%d.gamma);"%(index,u_index,u_index,u_index))
           
        output_list.append("%s_derivative_path(price_%d_%d,u_v_%d.time,&o_v_%d,&o_a_%d);" % (d.name,index,u_index,u_index,index,index)) #TODO - Some clever introspection to determine the composition of the call
        
        if("points" in self.derivative_attributes[index]):
	  for u in d.underlying:
	      u_index = self.underlying.index(u)
	      output_list.append("next_time_%d_%d = u_v_%d.time + o_v_%d.delta_time;" % (index,u_index,u_index,index))
        else:
	  for u in d.underlying:
	      u_index = self.underlying.index(u)
	      output_list.append("next_time_%d_%d = u_v_%d.time + o_v_%d.delta_time/%d;" % (index,u_index,u_index,index,self.solver_metadata["default_points"]))
        
        output_list.append("}")
    
    
    output_list.append("//***Determining Next Times for Underlyings***")
    for u in self.underlying:
        u_index = self.underlying.index(u)
        output_list.append("if((u_v_%d.time<o_a_%d.time_period)){"%(u_index,self.underlying_dependencies[u_index][0])) #setting very next time to the first active next time point
        output_list.append("very_next_time_%d=next_time_%d_%d;"%(u_index,self.underlying_dependencies[u_index][0],u_index))
        output_list.append("}")
        if(len(self.underlying_dependencies[u_index])>1): 
            for u_l in self.underlying_dependencies[u_index][1:]:
                output_list.append("if((u_v_%d.time<o_a_%d.time_period)&&(next_time_%d_%d<very_next_time_%d)){"%(u_index,u_l,u_l,u_index,u_index))
                output_list.append("very_next_time_%d=next_time_%d_%d;"%(u_index,u_l,u_index))
                output_list.append("}")
        
    output_list.append("//***Assesing whether loop is complete or not***")
    output_list.append("if(1")
    for d in self.derivative:
        index = self.derivative.index(d)
        for u in d.underlying:
            u_index = self.underlying.index(u)
            output_list.append(" && (u_v_%d.time>=o_a_%d.time_period)"%(u_index,index)) 
    output_list.append("){") #ending the loop if all underlyings are passed the time required by the derivatives
    output_list.append("done=0;")
    output_list.append("}")
    
    output_list.append("//***Calling Underlying Path Functions***")
    for u in self.underlying: #Calling the underlying path function
        u_index = self.underlying.index(u)
        output_list.append("if(u_v_%d.time<very_next_time_%d){"%(u_index,u_index))
        
        output_list.append("%s_underlying_path((very_next_time_%d-u_v_%d.time),&u_v_%d,&u_a_%d);" % (u.name,u_index,u_index,u_index,u_index))
        
        output_list.append("}")
    
    output_list.append("}") #End of Path Generation Loop
    
    output_list.append("//**Post path-generation calculations**")
    
    for d in self.derivative: #Post path-generation calculations
        index = self.derivative.index(d)
        for u in d.underlying:
            u_index = self.underlying.index(u)
            
            output_list.append("%s_derivative_payoff(price_%d_%d,&o_v_%d,&o_a_%d);"%(d.name,index,u_index,index,index))
            output_list.append("temp_total_%d += o_v_%d.value;"%(index,index))
            output_list.append("temp_total_sqrd_%d += pow(o_v_%d.value,2);"%(index,index))
            #output_list.append("printf(\"%%f\\n\",temp_value_sqrd_%d);"%index)
            
    output_list.append("}")
    #for d in self.derivative:
      #index = self.derivative.index(d)
      #output_list.append("FP_t temp_sample_std_dev_%d = pow((temp_value_sqrd_%d/temp_data->thread_paths-pow(temp_total_%d/temp_data->thread_paths,2))/(temp_data->thread_paths-1),0.5);"%(index,index,index))
      
      #output_list.append("FP_t temp_sample_std_error_%d = temp_sample_std_dev_%d/pow(temp_data->thread_paths,0.5);"%(index,index))
      
    ##Return result to main loop
    output_list.append("//**Returning Result**")
    for d in self.derivative: 
      output_list.append("((struct thread_data*) thread_arg)->thread_result[%d] = temp_total_%d;"%(self.derivative.index(d),self.derivative.index(d)))
      output_list.append("((struct thread_data*) thread_arg)->thread_result_sqrd[%d] = temp_total_sqrd_%d;"%(self.derivative.index(d),self.derivative.index(d)))
    output_list.append("}")
    
      
    return output_list
  
  def compile(self,overide=True,compile_options=[],debug=False):
    start_directory = os.getcwd()
    
    """
    try:
      os.chdir("..")
      os.chdir(self.platform.platform_directory())
      
    except:
      os.chdir(start_directory)
      return "%s doesn't exist!"%self.platform.platform_directory()
    """
    
    if(overide or not os.path.exists("%s%s%s"%(self.platform.root_directory(),self.platform.platform_directory(),self.output_file_name))):
        compile_cmd = ["g++","%s/%s.c"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name)]
	compile_cmd.append("-I%s%s"%(self.platform.root_directory(),self.platform.platform_directory()))
        #compile_cmd.append("-D%s"%self.platform.name.upper())
        compile_cmd.append("-DMULTICORE_CPU")

	if(self.random_number_generator=="taus_ziggurat"):
	  compile_cmd.append("-DTAUS_ZIGGURAT")
	elif(self.random_number_generator=="drand48_boxmuller"):
	  compile_cmd.append("-DDRAND48_BOXMULLER")
	elif(self.random_number_generator=="taus_boxmuller"):
	  compile_cmd.append("-DTAUS_BOXMULLER")
	 
        compile_cmd.append("-DFP_t=%s"%self.floating_point_format)
        #compile_cmd.append("-Dnative_sqrt=sqrt")
        #compile_cmd.append("-Dnative_exp=exp")
        #Including all of the derivative and option classes that are used
        temp = []
        for u in self.underlying:
            if(not(u.name in temp)):
                compile_cmd.append(("%s/%s.c" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),u.name)))
                temp.append(u.name)
            
            base_list = []
            self.generate_base_class_names(u.__class__,base_list)
            #base_list.remove("underlying")
        
            for b in base_list:
                if(b not in temp):
                    compile_cmd.append(("%s/%s.c" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),b)))
                    temp.append(b)
          
        compile_cmd.append("%s/gauss.c"%os.path.join(self.platform.root_directory(),self.platform.platform_directory()))
        for d in self.derivative:
            if(not(d.name in temp)):
                compile_cmd.append(("%s/%s.c" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),d.name)))
                temp.append(d.name)
                
            base_list = []
            self.generate_base_class_names(d.__class__,base_list)
            #base_list.remove("option")
                
            for b in base_list:
                if(b not in temp):
                    compile_cmd.append(("%s/%s.c" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),b)))
                    temp.append(b) 
        
        #Including all of the non system libraries used
        #for u_l in self.non_system_libraries:
            #if(not(("%s.c" % u_l) in compile_cmd)): compile_cmd.append(("%s.c" % u_l))
            
        
        #Linking pthread library
        compile_cmd.append("-lpthread")
        
        #RT
        if("darwin" not in sys.platform):compile_cmd.append("-lrt")
        
        #Optimisation Level 3
        compile_cmd.append("-O3")
        compile_cmd.append("-w")
        
        #SSE
        #compile_cmd.append("-msse3")
        
        
        #Fast Math
        compile_cmd.append("-ffast-math")
        
        #Permissive
        compile_cmd.append("-fpermissive")
        
        #Compile for this specific Machine (Linux only)
        if("darwin" not in sys.platform):compile_cmd.append("-march=native")
	
	#Adding other compile flags
        for c_o in compile_options: compile_cmd.append(c_o)
        
        #Output flag
        compile_cmd.append("-o")
        compile_cmd.append("%s/%s"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name))
	
	compile_string = ""
        for c_c in compile_cmd: compile_string = "%s %s"%(compile_string,c_c)
        if(debug): print compile_string
        
        result = subprocess.check_output(compile_cmd)
	
	#os.chdir(start_directory)
        #os.chdir(self.platform.root_directory())
        #os.chdir("bin")
        
        return result
      
    else:
      print "multicore binary already exists, using previous version. Set overide to True if you would like to force the code to be recompiled"
      #os.chdir(self.platform.root_directory)
      #os.chdir("bin")
          
  def execute(self,cleanup=False,debug=False,seed=int(random.randint(0,2**32-16))):
    """
    try:
      os.chdir("..")
      os.chdir(self.platform.platform_directory())
    except:
      os.chdir("bin")
      return "Multicore C directory doesn't exist!"
    """

    self.solver_metadata["rng_seed"] = seed

    run_cmd = ["%s/%s"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name)]
    for k in sorted(self.solver_metadata): run_cmd.append(str(self.solver_metadata[k])) 
    
    for index,u_a in enumerate(self.underlying_attributes):
        for a in u_a: run_cmd.append(str(self.underlying[index].__dict__[a])) #mirrors generation code to preserve order of variable loading
    
    for index,o_a in enumerate(self.derivative_attributes): 
        for a in o_a: run_cmd.append(str(self.derivative[index].__dict__[a]))

    run_string = ""
    for r_c in run_cmd: run_string = "%s %s"%(run_string,r_c)
    if(debug): print run_string
    
    start = time.time() #Wall-time is measured by framework, as well as in the generated application to measure overhead in calling code
    results = subprocess.check_output(run_cmd)
    finish = time.time()
    
    results = results.split("\n")[:-1]
    results.append((finish-start)*1000000)
    
    """
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    """
    
    if(cleanup): self.cleanup()
    
    return results
  
  def cleanup(self):
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    subprocess.call(["rm","%s.c"%self.output_file_name])
    subprocess.call(["rm","%s"%self.output_file_name])
  
  def generate_source(self,code_string,name_extension=".c",verbose=False,debug=False):
    #os.chdir("..")
    #os.chdir(self.platform.platform_directory())
    
    temp_filename = "%s/%s%s"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name,name_extension)
    if(debug): print("Generated %s"%temp_filename)
    output_file = open(temp_filename,"w")
    tab_count = 0;
    for c_s in code_string:
        if("*" in c_s and "//" in c_s):
          output_file.write("\n") #Insert a blank line if the line is a comment section
          
          if(verbose and "**" in c_s):
            for i in range(tab_count): output_file.write("\t")	#Tabify the code
            output_file.write("printf(\"%s\\n\");\n"%c_s.strip("/")) #If verbose, print out comment to help locate errors
        
        for i in range(tab_count): output_file.write("\t")	#Tabify the code
        output_file.write("%s\n"%c_s)
            
        if("{" in c_s): tab_count = tab_count+1
        if("}" in c_s): tab_count = max(tab_count-1,0)
    output_file.close()
    
    #os.chdir(self.platform.root_directory())
    #os.chdir("bin")
  
  def generate_base_class_names(self,tempclass,templist):
    """Another Helper Method, uses to help pull in various super classes during compilation """
    if(tempclass.name not in templist): templist.append(tempclass.name)
    for b in tempclass.__bases__: self.generate_base_class_names(b,templist)
