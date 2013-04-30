'''
Created on 23 February 2013

'''
import os,time,subprocess,sys,time,math,pyopencl
from ForwardFinancialFramework.Platforms.MulticoreCPU import MulticoreCPU_MonteCarlo

class OpenCLGPU_MonteCarlo(MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo):
  def __init__(self,derivative,paths,platform,reduce_underlyings=True):
    MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.__init__(self,derivative,paths,platform,reduce_underlyings)
    
    self.utility_libraries.extend(["CL/cl.hpp"])
    self.activity_thread_name = "opencl_montecarlo_activity_thread"
    
    self.kernel_code_string = ""
    
    #TODO where must this go?
    path_points = 0
    for index,d in enumerate(self.derivative):
      if("points" in self.derivative_attributes[index]):
	if((d.points!=path_points) and not(path_points)): raise IOError, ("For an OpenCL solver the number of path points must match")
	elif(not(path_points)): path_points = d.points
	
    if(path_points): self.solver_metadata["path_points"] = path_points
    else: self.solver_metadata["path_points"] = self.solver_metadata["default_points"]
  
  def generate_identifier(self): return ["//%s.c Generated by Monte Carlo Maxeler Solver"%self.output_file_name]
  
  def generate(self,override=True):
    #Generate C Host Code largely using Multicore C infrastructure
    MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.generate(self,".c",override,verbose=False)
    
    #Generate OpenCL Kernel Code
    self.kernel_code_string = self.generate_kernel()
  
  def generate_activity_thread(self):
    output_list = []

    output_list.append("//*MC OpenCL Activity Thread Function*")
    output_list.append("void * %s(void* thread_arg){"%self.activity_thread_name)
    output_list.append("struct thread_data* temp_data;")
    output_list.append("temp_data = (struct thread_data*) thread_arg;")
        
    ##Declaring OpenCL Data Structures
    output_list.append("//**Creating OpenCL Infrastructure**")
    
    ###Creating OpenCL Platform
    #TODO Use PyOpenCL to find this information out
    output_list.append("//***Creating Platform***")
    output_list.append("cl_uint num_platforms;");
    output_list.append("clGetPlatformIDs(0, NULL, &num_platforms);")
    output_list.append("cl_platform_id* platform_id = (cl_platform_id*)malloc(sizeof(cl_platform_id) * num_platforms);")
    output_list.append("cl_platform_id platform = NULL;")
    output_list.append("clGetPlatformIDs(num_platforms, platform_id, &num_platforms);")
    output_list.append("for(unsigned int i = 0; i < num_platforms; ++i){")
    output_list.append("char pbuff[100];")
    output_list.append("clGetPlatformInfo(platform_id[i],CL_PLATFORM_VENDOR,sizeof(pbuff),pbuff,NULL);")
    output_list.append("platform = platform_id[i];")
    output_list.append("if(!strcmp(pbuff, \"%s\")){break;}"%(self.platform.platform_name))
    output_list.append("}")
    
    ###Creating OpenCL Context
    output_list.append("//***Creating Context***")
    output_list.append("cl_context_properties cps[3] = { CL_CONTEXT_PLATFORM, (cl_context_properties)platform, 0 };")
    output_list.append("cl_context context = clCreateContextFromType(cps, CL_DEVICE_TYPE_%s, NULL, NULL, NULL);"%pyopencl.device_type.to_string(self.platform.device_type))
    
    ###Creating OpenCL Device
    output_list.append("//***Creating Device***")
    output_list.append("size_t deviceListSize;")
    output_list.append("clGetContextInfo(context,CL_CONTEXT_DEVICES,0, NULL,&deviceListSize);")
    output_list.append("cl_device_id *devices = (cl_device_id *)malloc(deviceListSize);")
    output_list.append("clGetContextInfo(context, CL_CONTEXT_DEVICES, deviceListSize,devices,NULL);")
    output_list.append("cl_device_id device = devices[0];")
     
    ###Creating the OpenCL Program from the precompiled binary
    output_list.append("//***Creating Programt***")
    output_list.append("FILE *fp=fopen(\"%s.clbin\", \"r\");"%self.output_file_name)
    output_list.append("char *binary_buf = (char *)malloc(0x100000);")
    output_list.append("size_t binary_size = fread(binary_buf, 1, 0x100000, fp);")
    output_list.append("fclose(fp);")
    output_list.append("cl_program program = clCreateProgramWithBinary(context, 1, &device, (const size_t *)&binary_size,(const unsigned char **)&binary_buf, NULL, NULL);")
    #output_list.append("clBuildProgram(program, 1, &device, NULL, NULL, NULL);")
    
    ###Creating the OpenCL Kernel
    output_list.append("//***Creating Kernel Object***")
    output_list.append("cl_kernel %s_kernel = clCreateKernel(program,\"%s_kernel\",NULL);"%(self.output_file_name,self.output_file_name))
    
    ###Creating the Memory Objects for each underlying and derivative
    #TODO Maybe there should an attribute memory object for each path, instead of one shared between all
    output_list.append("//***Creating OpenCL Memory Objects***")
    output_list.append("cl_mem path_points_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(cl_int),NULL,NULL);")
    for index,u in enumerate(self.underlying):
        output_list.append("%s_under_attr u_a_%d[1];" % (u.name,index))
        output_list.append("cl_mem u_a_%d_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(%s_under_attr),NULL,NULL);" % (index,u.name))
        output_list.append("%s_under_var u_v_%d[temp_data->thread_paths];" % (u.name,index)) #Mallocs, here?
        output_list.append("cl_mem u_v_%d_buff = clCreateBuffer(context, CL_MEM_READ_WRITE,temp_data->thread_paths*sizeof(%s_under_var),NULL,NULL);" % (index,u.name))
    
    for index,d in enumerate(self.derivative):
        output_list.append("%s_opt_attr o_a_%d[1];" % (d.name,index))
        output_list.append("cl_mem o_a_%d_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(%s_opt_attr),NULL,NULL);" % (index,d.name))
        output_list.append("%s_opt_var o_v_%d[temp_data->thread_paths];" % (d.name,index)) #Mallocs, here?
        output_list.append("cl_mem o_v_%d_buff = clCreateBuffer(context, CL_MEM_READ_WRITE,temp_data->thread_paths*sizeof(%s_opt_var),NULL,NULL);" % (index,d.name))
    
    ##Binding the Memory Objects to the Kernel
    output_list.append("//**Setting Kernel Arguments**")
    output_list.append("clSetKernelArg(%s_kernel, 0, sizeof(cl_int), (void *)&path_points_buff);"%(self.output_file_name))
    
    for index,u in enumerate(self.underlying):
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&u_a_%d_buff);"%(self.output_file_name,1 + index*2,index))
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&u_v_%d_buff);"%(self.output_file_name,1 + index*2+1,index))
      
    for index,d in enumerate(self.derivative):
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&o_a_%d_buff);"%(self.output_file_name,1 + index*2 + 2*len(self.underlying),index))
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&o_v_%d_buff);"%(self.output_file_name,1 + index*2+1 + 2*len(self.underlying),index))
    
    ##Creating the Command Queue for the Kernel
    output_list.append("//**Creating OpenCL Command Queue**")
    output_list.append("cl_command_queue command_queue = clCreateCommandQueue(context, device, 0, &ret);")
    
    output_list.append("//**Initialising Attributes and writing to OpenCL Memory Object**")
    ###Writing Control Parameter
    output_list.append("clEnqueueWriteBuffer(command_queue, path_points_buff, CL_TRUE, 0, sizeof(cl_int), &path_points, 0, NULL, NULL);")
    output_list.append("clFinish(command_queue);")
    ###Calling Init Functions
    for u_index,u in enumerate(self.underlying):
        temp = ("%s_underlying_init("%u.name)
        for u_a in self.underlying_attributes[u_index][:-1]: temp=("%s%s_%d_%s,"%(temp,u.name,u_index,u_a))
        temp=("%s%s_%d_%s,u_a_%d);"%(temp,u.name,u_index,self.underlying_attributes[u_index][-1],u_index))   
        output_list.append(temp)
        output_list.append("clEnqueueWriteBuffer(command_queue, u_a_%d_buff, CL_TRUE, 0, sizeof(u_a_%d), u_a_%d, 0, NULL, NULL);"%(u_index,u_index,u_index))
	output_list.append("clFinish(command_queue);")
    
    for d_index,d in enumerate(self.derivative):
        temp = ("%s_derivative_init("%d.name)
        for o_a in self.derivative_attributes[index][:-1]: temp=("%s%s_%d_%s,"%(temp,d.name,index,o_a))
        temp=("%s%s_%d_%s,o_a_%d);"%(temp,d.name,index,self.derivative_attributes[index][-1],index))
        output_list.append(temp)
        output_list.append("clEnqueueWriteBuffer(command_queue, o_a_%d_buff, CL_TRUE, 0, sizeof(o_a_%d), o_a_%d, 0, NULL, NULL);"%(d_index,d_index,d_index))
        output_list.append("clFinish(command_queue);")
      
    ##Running the actual kernel
    output_list.append("//**Run the kernel**")
    output_list.append("size_t kernel_paths = temp_data->thread_paths;")
    output_list.append("clEnqueueNDRangeKernel(command_queue, %s_kernel, 1, NULL, kernel_paths, NULL, 0, NULL, NULL);"%(self.output_file_name))
    output_list.append("clFinish(command_queue);")
    
    ##Reading the Results out from the derivative objects
    output_list.append("//**Reading the results**")
    for d_index,d in enumerate(self.derivative):
        output_list.append("clEnqueueReadBuffer(command_queue, o_v_%d_buff, CL_TRUE, 0, temp_data->thread_paths * sizeof(%s_opt_var),o_v_%d, 0, NULL, NULL);"%(d_index,d.name,d_index))
	output_list.append("clFinish(command_queue);")
    
    output_list.append("//**Post-Kernel Calculations**")
    for d in range(len(self.derivative)): 
      output_list.append("double temp_total_%d=0;"%d)
      output_list.append("double temp_value_sqrd_%d=0;"%d)
    output_list.append("for(int i=0;i<paths;i++){")
    for index,d in enumerate(self.derivative):
      output_list.append("temp_total_%d += o_v_%d->value;"%(index,index))
      output_list.append("temp_value_sqrd_%d += pow(o_v_%d->value,2);"%(index,index))
    output_list.append("}")
    
    output_list.append("//**Returning Result**")
    #output_list.append("printf(\"temp_total=%f\",temp_total_0);")
    for d in self.derivative: 
      output_list.append("temp_data->thread_result[%d] = temp_total_%d;"%(self.derivative.index(d),self.derivative.index(d)))
      output_list.append("temp_data->thread_result_sqrd[%d] = temp_value_sqrd_%d;"%(self.derivative.index(d),self.derivative.index(d)))
    output_list.append("}")
    
    return output_list
  
  """def generate_libraries(self):
    output_list = ["//*Libraries"]
    output_list.append("#define __STDC_FORMAT_MACROS")
    for u in self.utility_libraries: output_list.append("#include \"%s\";"%u)
    
    return output_list"""
  
  def generate_kernel(self):
    output_list = []
    
    #Changing to code generation directory for underlying and derivatives
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    #Checking that the source code for the derivative and underlying required is avaliable
    for u in self.underlying: 
      if(not(os.path.exists("%s.c"%u.name)) or not(os.path.exists("%s.h"%u.name))): raise IOError, ("missing the source code for the underlying - %s.c or %s.h" % (u.name,u.name))
      else: output_list.append("#include \"%s.h\""%u.name)
        
    for d in self.derivative:
      if(not(os.path.exists("%s.c"%d.name)) or not(os.path.exists("%s.h"%d.name))): raise IOError, ("missing the source code for the derivative - %s.c or %s.h" %  (d.name,d.name))
      else: output_list.append("#include \"%s.h\""%d.name)    
    #Leaving code generation directory
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
    output_list.append("kernel void %s_kernel(global int *path_points,"%self.output_file_name)
    for index,u in enumerate(self.underlying):
      output_list.append("\tglobal %s_under_attr *u_a_%d,"%(u.name,index))
      output_list.append("\tglobal %s_under_var *u_v_%d,"%(u.name,index))
      
    for index,d in enumerate(self.derivative):
      output_list.append("\tglobal %s_opt_attr *o_a_%d,"%(d.name,index))
      if(index<(len(self.derivative)-1)): output_list.append("\tglobal %s_opt_var *o_v_%d,"%(d.name,index))
      else: output_list.append("\tglobal %s_opt_var *o_v_%d) {"%(d.name,index))
    
    output_list.append("int i = get_global_id(0);")
    output_list.append("int local_path_points=path_points[0];")
    for index,u in enumerate(self.underlying):
      output_list.append("%s_under_attr local_u_a_%d = u_a_%d[0];"%(u.name,index,index))
      output_list.append("%s_under_var local_u_v_%d = u_v_%d[i];"%(u.name,index,index))
      
    for index,d in enumerate(self.derivative):
      output_list.append("%s_opt_attr local_o_a_%d = o_a_%d[0];"%(d.name,index,index))
      output_list.append("%s_opt_var local_o_v_%d = o_v_%d[i];"%(d.name,index,index))
    
    for index,u in enumerate(self.underlying): 
        output_list.append("%s_underlying_path_init(&local_u_v_%d,&local_u_a_%d);" % (u.name,index,index))
        output_list.append("double spot_price_%d = local_u_a_%d.current_price*exp(local_u_v_%d.gamma);"%(index,index,index))
        output_list.append("double time_%d = local_u_v_%d.time;"%(index,index))
    
    for index,d in enumerate(self.derivative):
        output_list.append("%s_derivative_path_init(&local_o_v_%d,&local_o_a_%d);" % (d.name,index,index))
        
        #If a derivative doesn't have the number of path points specified, its delta time needs to be set to reflect what is the default points or that of the other derivatives
	if("points" not in self.derivative_attributes[index]): output_list.append("local_o_v_%d.delta_time = local_o_a_%d.time_period/local_path_points;"%(index,index))
	
    output_list.append("for(int j=0;j<local_path_points;++j){")
    
    temp_underlying = self.underlying[:]
    for index,d in enumerate(self.derivative):
      for u in d.underlying: #Calling derivative and underlying path functions
	u_index = self.underlying.index(u)
	output_list.append("%s_derivative_path(spot_price_%d,time_%d,&local_o_v_%d,&local_o_a_%d);" % (d.name,u_index,u_index,index,index))
	
	if(u in temp_underlying):
	  output_list.append("%s_underlying_path(local_o_v_%d.delta_time,&local_u_v_%d,&local_u_a_%d);" % (u.name,index,u_index,u_index))
	  temp_underlying.remove(u)
	  
	  output_list.append("spot_price_%d = local_u_a_%d.current_price*exp(local_u_v_%d.gamma);"%(u_index,u_index,u_index))
	  output_list.append("time_%d = local_u_v_%d.time;"%(u_index,u_index))
    
    output_list.append("}") #End of For Loop
    
    for index,d in enumerate(self.derivative):
      for u in d.underlying:
	u_index = self.underlying.index(u)
	output_list.append("%s_derivative_payoff(spot_price_%d,&local_o_v_%d,&local_o_a_%d);"%(d.name,u_index,index,index))
	output_list.append("o_v_%d[i] = local_o_v_%d;"%(index,index))
    
    output_list.append("}") #End of Kernel
    
    #Turning output list into output string
    output_string = output_list[0]
    for line in output_list[1:]: output_string = "%s\n%s"%(output_string,line)
    output_string = "%s\n"%(output_string) #Adding newline to end of file
    
    return output_string
      
  def compile(self,override=True,cleanup=True):
    
    result = MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.compile(self,override,["-lOpenCL","-I/opt/AMDAPP/include","-fpermissive"]) #Compiling Host C Code
      
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    #print self.kernel_code_string
    """self.program = pyopencl.Program(self.platform.context,self.kernel_code_string).build(["-I."]) #Creating OpenCL program based upon Kernel
    binary_kernel = self.program.get_info(pyopencl.program_info.BINARIES)[0] #Getting the binary code for the OpenCL code
    binary_kernel_file = open("%s.clbin"%self.output_file_name,"wb") #Writing the binary code to a file to be read by the Host C Code
    binary_kernel_file.write(binary_kernel)
    binary_kernel_file.close()"""
    kernel_file = open("%s.cl"%self.output_file_name,"w")
    kernel_file.write(self.kernel_code_string)
    kernel_file.close()
    
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
      
    return result
  
      
  """def compile(self,override=True,cleanup=True):
    try:
      os.chdir("..")
      os.chdir(self.platform.platform_directory())
      
    except:
      os.chdir("bin")
      return "Maxeler Code directory doesn't exist!"
    
    if(override or not os.path.exists("hardware/%s/"%self.output_file_name)):
      #Hardware Build Process
      compile_cmd = ["make","build-hw","APP=%s"%self.output_file_name]
      hw_result = subprocess.check_output(compile_cmd)
      #subprocess.check_output(["rm -r ../../scratch/*"]) #cleaning up majority of HDL source code generated for synthesis
      #print hw_result
      
      #Host Code Compile
      compile_cmd = ["make","app-hw","APP=%s"%self.output_file_name]
      sw_result = subprocess.check_output(compile_cmd)
      #print sw_result
      
      os.chdir(self.platform.root_directory())
      os.chdir("bin")
      
      return (hw_result,sw_result)"""
      
  def execute(self,cleanup=False):
    try:
      os.chdir("..")
      os.chdir(self.platform.platform_directory())
      
    except:
      os.chdir("bin")
      return "OpenCL code directory doesn't exist!"
    
    run_cmd = ["./%s"%self.output_file_name]
    for k in self.solver_metadata.keys(): run_cmd.append(str(self.solver_metadata[k]))
    
    index = 0
    for u_a in self.underlying_attributes:
        for a in u_a: run_cmd.append(str(self.underlying[index].__dict__[a])) #mirrors generation code to preserve order of variable loading
        index += 1
    
    index = 0
    for o_a in self.derivative_attributes: 
        for a in o_a: run_cmd.append(str(self.derivative[index].__dict__[a]))
        index +=1
    
    start = time.time() #Wall-time is measured by framework, not the generated application to measure overhead in calling code
    results = subprocess.check_output(run_cmd)
    finish = time.time()
    
    results = results.split("\n")[:-1]
    results.append((finish-start)*1000000)
    
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
    if(cleanup): self.cleanup()
    
    return results
    
    
  """def generate_java_source(self,code_string,name_extension=""):
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    output_file = open("%s%s.java"%(self.output_file_name,name_extension),"w")
    tab_count = 0;
    for c_s in code_string:
        if("*" in c_s and "//" in c_s): output_file.write("\n") #Insert a blank line if the line is a comment section
        for i in range(tab_count): output_file.write("\t")	#Tabify the code
        output_file.write("%s\n"%c_s)
            
        if("{" in c_s): tab_count = tab_count+1
        if("}" in c_s): tab_count = max(tab_count-1,0)
    output_file.close()
    
    os.chdir(self.platform.root_directory())
    os.chdir("bin")"""