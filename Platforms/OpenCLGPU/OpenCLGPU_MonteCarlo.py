'''
Created on 23 February 2013

'''
import os,time,subprocess,sys,time,math,pyopencl
import platform as plat
from ForwardFinancialFramework.Platforms.MulticoreCPU import MulticoreCPU_MonteCarlo

class OpenCLGPU_MonteCarlo(MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo):
  def __init__(self,derivative,paths,platform,reduce_underlyings=True):
    MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.__init__(self,derivative,paths,platform,reduce_underlyings)
    
    if("Darwin" in plat.system()): self.utility_libraries.extend(["OpenCL/opencl.h"])
    else: self.utility_libraries.extend(["CL/cl.hpp"])
    self.activity_thread_name = "opencl_montecarlo_activity_thread"
    
    self.kernel_code_string = ""
    self.cpu_seed_kernel_code_string = ""
    
    #Setting the number of points in the path, as determined by the derivatives passed to the solver
    #TODO where must this go? Probably somewhere that it will get called everytime the generate command is called
    path_points = 0
    for index,d in enumerate(self.derivative):
      if("points" in self.derivative_attributes[index]):
	if((d.points!=path_points) and path_points): raise IOError, ("For an OpenCL solver the number of path points must match")
	elif(not(path_points)): path_points = d.points
	
    if(path_points): self.solver_metadata["path_points"] = path_points
    else: self.solver_metadata["path_points"] = self.solver_metadata["default_points"]
  
  def generate_identifier(self): return ["//%s.c Generated by Monte Carlo Maxeler Solver"%self.output_file_name]
  
  def generate(self,override=True):
    #Generate C Host Code largely using Multicore C infrastructure
    MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.generate(self,".c",override,verbose=False)
    
    #Generate OpenCL Kernel Code
    self.kernel_code_list = self.generate_kernel()
    self.generate_source(self.kernel_code_list,".cl")
    
    #If using an AMD Platform, Generate OpenCL Kernel Code for seeding using the Host CPU
    if("AMD" in self.platform.platform_name):
      self.cpu_seed_kernel_code_list = self.generate_cpu_seed_kernel()
      self.generate_source(self.cpu_seed_kernel_code_list,"_cpu_seed.cl")
  
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
    
    if("AMD" in self.platform.platform_name):
      ###Creating OpenCL CPU Context
      output_list.append("//***Creating CPU Context***")
      output_list.append("cl_context_properties cpu_cps[3] = { CL_CONTEXT_PLATFORM, (cl_context_properties)platform, 0 };")
      output_list.append("cl_context cpu_context = clCreateContextFromType(cpu_cps, CL_DEVICE_TYPE_CPU, NULL, NULL, NULL);")
    
    ###Creating OpenCL Device
    output_list.append("//***Creating Device***")
    output_list.append("size_t deviceListSize;")
    output_list.append("clGetContextInfo(context,CL_CONTEXT_DEVICES,0, NULL,&deviceListSize);")
    output_list.append("cl_device_id *devices = (cl_device_id *)malloc(deviceListSize);")
    output_list.append("clGetContextInfo(context, CL_CONTEXT_DEVICES, deviceListSize,devices,NULL);")
    output_list.append("cl_device_id device = devices[0];")
    
    if("AMD" in self.platform.platform_name):
      output_list.append("//***Creating CPU Device***")
      output_list.append("clGetContextInfo(cpu_context,CL_CONTEXT_DEVICES,0, NULL,&deviceListSize);")
      output_list.append("cl_device_id *cpu_devices = (cl_device_id *)malloc(deviceListSize);")
      output_list.append("clGetContextInfo(cpu_context, CL_CONTEXT_DEVICES, deviceListSize,cpu_devices,NULL);")
      output_list.append("cl_device_id cpu_device = cpu_devices[0];")
     
    ###Creating the OpenCL Program from the precompiled binary
    output_list.append("//***Creating Program***")
    output_list.append("FILE *fp=fopen(\"%s.clbin\", \"r\");"%self.output_file_name)
    output_list.append("char *binary_buf = (char *)malloc(0x100000);")
    output_list.append("size_t binary_size = fread(binary_buf, 1, 0x100000, fp);")
    output_list.append("fclose(fp);")
    output_list.append("cl_program program = clCreateProgramWithBinary(context, 1, &device, (const size_t *)&binary_size,(const unsigned char **)&binary_buf, NULL, NULL);")
    output_list.append("clBuildProgram(program, 1, &device, NULL, NULL, NULL);")
    
    if("AMD" in self.platform.platform_name):
      ###Creating the OpenCL CPU Program from the precompiled binary
      output_list.append("//***Creating CPU Program***")
      output_list.append("FILE *cpu_fp=fopen(\"%s_cpu_seed.clbin\", \"r\");"%self.output_file_name)
      output_list.append("char *cpu_binary_buf = (char *)malloc(0x100000);")
      output_list.append("size_t cpu_binary_size = fread(cpu_binary_buf, 1, 0x100000, cpu_fp);")
      output_list.append("fclose(cpu_fp);")
      output_list.append("cl_program cpu_program = clCreateProgramWithBinary(cpu_context, 1, &cpu_device, (const size_t *)&cpu_binary_size,(const unsigned char **)&cpu_binary_buf, NULL, NULL);")
      output_list.append("clBuildProgram(cpu_program, 1, &cpu_device, NULL, NULL, NULL);")
    
    """output_list.append("FILE *fp;")
    output_list.append("char *source_str;")
    output_list.append("size_t source_size;")
    output_list.append("fp=fopen(\"%s.cl\",\"r\");"%self.output_file_name)
    output_list.append("source_str = (char *)malloc(0x100000);")
    output_list.append("source_size = fread(source_str, 1, 0x100000, fp);")
    output_list.append("fclose(fp);")
    output_list.append("cl_program program = clCreateProgramWithSource(context, 1, (const char **)&source_str, (const size_t *)&source_size, &ret);")
    output_list.append("const char* buildOption =\"-I . -I mwc64x/cl\";") #-x clc++
    output_list.append("ret = clBuildProgram(program, 1, &device, buildOption, NULL, NULL);")"""
    #output_list.append("clBuildProgram(program, 1, &device, NULL, NULL, NULL);")"""

   ###Outputing the Build Log
    """output_list.append("size_t ret_val_size;")
    output_list.append("clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, 0, NULL, &ret_val_size);")   
    output_list.append("char build_log[ret_val_size+1];")
    output_list.append("clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,sizeof(build_log),build_log,NULL);")
    output_list.append("build_log[ret_val_size] = '\0';")
    output_list.append("printf(\"OpenCL Build Log: %s\\n\",build_log);")"""

    ###Creating the OpenCL Kernel
    output_list.append("//***Creating Kernel Object***")
    output_list.append("cl_kernel %s_kernel = clCreateKernel(program,\"%s_kernel\",&ret);"%(self.output_file_name,self.output_file_name))
    
    if("AMD" in self.platform.platform_name):
      ###Creating the OpenCL CPU Kernel
      output_list.append("//***Creating Kernel Object***")
      output_list.append("cl_kernel %s_cpu_seed_kernel = clCreateKernel(cpu_program,\"%s_cpu_seed_kernel\",&ret);"%(self.output_file_name,self.output_file_name))
      
    #output_list.append("printf(\"%d\\n\",ret);")
    
    ###Creating the Memory Objects for each underlying and derivative
    #TODO Maybe there should an attribute memory object for each path, instead of one shared between all
    output_list.append("//***Creating OpenCL Memory Objects***")
    output_list.append("cl_mem path_points_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(cl_int),NULL,NULL);")
    for index,u in enumerate(self.underlying):
        output_list.append("%s_attributes u_a_%d[1];" % (u.name,index))
        output_list.append("cl_mem u_a_%d_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(%s_attributes),NULL,NULL);" % (index,u.name))
        output_list.append("cl_mem u_v_%d_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,temp_data->thread_paths*sizeof(mwc64x_state_t),NULL,NULL);" % (index))
        if("AMD" in self.platform.platform_name):
          output_list.append("mwc64x_state_t *u_v_%d = (mwc64x_state_t*) malloc(temp_data->thread_paths*sizeof(mwc64x_state_t));" % (index)) #Mallocs, here?
          output_list.append("cl_mem cpu_u_v_%d_buff = clCreateBuffer(cpu_context, CL_MEM_WRITE_ONLY,temp_data->thread_paths*sizeof(mwc64x_state_t),NULL,NULL);" % (index))
    
    for index,d in enumerate(self.derivative):
        output_list.append("%s_attributes o_a_%d[1];" % (d.name,index))
        output_list.append("cl_mem o_a_%d_buff = clCreateBuffer(context, CL_MEM_READ_ONLY,sizeof(%s_attributes),NULL,NULL);" % (index,d.name))
        output_list.append("%s_variables *o_v_%d = (%s_variables*) malloc(temp_data->thread_paths*sizeof(%s_variables));" % (d.name,index,d.name,d.name)) #Mallocs, here?
        output_list.append("cl_mem o_v_%d_buff = clCreateBuffer(context, CL_MEM_WRITE_ONLY,temp_data->thread_paths*sizeof(%s_variables),NULL,NULL);" % (index,d.name))
    
    ##Binding the Memory Objects to the Kernel
    output_list.append("//**Setting Kernel Arguments**")
    output_list.append("clSetKernelArg(%s_kernel, 0, sizeof(cl_mem), (void *)&path_points_buff);"%(self.output_file_name))
    
    for index,u in enumerate(self.underlying):
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&u_a_%d_buff);"%(self.output_file_name,1 + index*2,index))
      #output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(sizeof(%s_attributes)), NULL);"%(self.output_file_name,1 + index*4+1,u.name))
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&u_v_%d_buff);"%(self.output_file_name,1 + index*2+1,index))
      #output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(temp_data->thread_paths*sizeof(%s_variables)), NULL);"%(self.output_file_name,1 + index*4+3,u.name))
      
    for index,d in enumerate(self.derivative):
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&o_a_%d_buff);"%(self.output_file_name,1 + index*2 + 2*len(self.underlying),index))
      #output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(sizeof(%s_attributes)), NULL);"%(self.output_file_name,1 + index*4+1+ 4*len(self.underlying),d.name))
      output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&o_v_%d_buff);"%(self.output_file_name,1 + index*2 + 1 + 2*len(self.underlying),index))
      #output_list.append("clSetKernelArg(%s_kernel, %d, sizeof(temp_data->thread_paths*sizeof(%s_variables)), NULL);"%(self.output_file_name,1 + index*4+3 + 4*len(self.underlying),d.name))
    
    if("AMD" in self.platform.platform_name):
      for index,u in enumerate(self.underlying):
        output_list.append("clSetKernelArg(%s_cpu_seed_kernel, %d, sizeof(mwc64x_state_t)*temp_data->thread_paths, NULL);"%(self.output_file_name,2*index))
        output_list.append("clSetKernelArg(%s_cpu_seed_kernel, %d, sizeof(cl_mem), (void *)&cpu_u_v_%d_buff);"%(self.output_file_name,1 + 2*index,index))
        
    
    ##Creating the Command Queue for the Kernel
    output_list.append("//**Creating OpenCL Command Queue**")
    output_list.append("cl_command_queue command_queue = clCreateCommandQueue(context, device, 0, &ret);")
    
    if("AMD" in self.platform.platform_name):
      output_list.append("cl_command_queue cpu_command_queue = clCreateCommandQueue(cpu_context, cpu_device, 0, &ret);")
      
    if("AMD" in self.platform.platform_name):
      output_list.append("const size_t cpu_kernel_paths = temp_data->thread_paths;")
      output_list.append("clEnqueueNDRangeKernel(cpu_command_queue, %s_cpu_seed_kernel, (cl_uint) 1, NULL, &cpu_kernel_paths, NULL, 0, NULL, NULL);"%(self.output_file_name))
    
    output_list.append("//**Initialising Attributes and writing to OpenCL Memory Object**")
    ###Writing Control Parameter
    output_list.append("cl_int *path_points_array = (cl_int*)malloc(sizeof(cl_int));")
    output_list.append("path_points_array[0] = path_points;")
    output_list.append("clEnqueueWriteBuffer(command_queue, path_points_buff, CL_TRUE, 0, sizeof(cl_int), path_points_array, 0, NULL, NULL);")
    output_list.append("clFinish(command_queue);")
    ###Calling Init Functions
    for u_index,u in enumerate(self.underlying):
        temp = ("%s_underlying_init("%u.name)
        for u_a in self.underlying_attributes[u_index][:-1]: temp=("%s%s_%d_%s,"%(temp,u.name,u_index,u_a))
        temp=("%s%s_%d_%s,u_a_%d);"%(temp,u.name,u_index,self.underlying_attributes[u_index][-1],u_index))   
        output_list.append(temp)
        output_list.append("clEnqueueWriteBuffer(command_queue, u_a_%d_buff, CL_TRUE, 0, sizeof(%s_attributes), u_a_%d, 0, NULL, NULL);"%(u_index,u.name,u_index))
	output_list.append("clFinish(command_queue);")
    
    for d_index,d in enumerate(self.derivative):
        temp = ("%s_derivative_init("%d.name)
        for o_a in self.derivative_attributes[d_index][:-1]: temp=("%s%s_%d_%s,"%(temp,d.name,d_index,o_a))
        temp=("%s%s_%d_%s,o_a_%d);"%(temp,d.name,d_index,self.derivative_attributes[d_index][-1],d_index))
        output_list.append(temp)
        output_list.append("clEnqueueWriteBuffer(command_queue, o_a_%d_buff, CL_TRUE, 0, sizeof(%s_attributes), o_a_%d, 0, NULL, NULL);"%(d_index,d.name,d_index))
        output_list.append("clFinish(command_queue);")
      
      #for index,u in enumerate(self.underlying):
        #output_list.append("clEnqueueReadBuffer(cpu_command_queue, u_v_%d_buff, CL_TRUE, 0, temp_data->thread_paths * sizeof(%s_variables),u_v_%d, 0, NULL, NULL);"%(index,u.name,index))
	#output_list.append("clFinish(command_queue);")
    
    if("AMD" in self.platform.platform_name):
      output_list.append("clFinish(cpu_command_queue);")
      
      for index,u in enumerate(self.underlying):
        output_list.append("clEnqueueReadBuffer(cpu_command_queue, cpu_u_v_%d_buff, CL_TRUE, 0, temp_data->thread_paths * sizeof(mwc64x_state_t),u_v_%d, 0, NULL, NULL);"%(index,index))
        output_list.append("clFinish(cpu_command_queue);")
        output_list.append("clEnqueueWriteBuffer(command_queue, u_v_%d_buff, CL_TRUE, 0, temp_data->thread_paths * sizeof(mwc64x_state_t), u_v_%d, 0, NULL, NULL);"%(index,index))
    
      output_list.append("clFinish(command_queue);")
      
    
    ##Running the actual kernel
    output_list.append("//**Run the kernel**")
    output_list.append("const size_t kernel_paths = temp_data->thread_paths;")
    output_list.append("clEnqueueNDRangeKernel(command_queue, %s_kernel, (cl_uint) 1, NULL, &kernel_paths, NULL, 0, NULL, NULL);"%(self.output_file_name))
    output_list.append("clFinish(command_queue);")
    
    ##Reading the Results out from the derivative objects
    output_list.append("//**Reading the results**")
    for d_index,d in enumerate(self.derivative):
        output_list.append("clEnqueueReadBuffer(command_queue, o_v_%d_buff, CL_TRUE, 0, temp_data->thread_paths * sizeof(%s_variables),o_v_%d, 0, NULL, NULL);"%(d_index,d.name,d_index))
	output_list.append("clFinish(command_queue);")
    
    output_list.append("//**Post-Kernel Calculations**")
    for d in range(len(self.derivative)): 
      output_list.append("double temp_total_%d=0;"%d)
      output_list.append("double temp_value_sqrd_%d=0;"%d)
    output_list.append("for(int i=0;i<paths;i++){")
    for index,d in enumerate(self.derivative):
      #output_list.append("printf(\"%%f\\n\",o_a_%d[0].time_period);"%index)
      #output_list.append("printf(\"%%f\\n\",o_v_%d[i].delta_time);"%index)
      output_list.append("temp_total_%d += o_v_%d[i].value;"%(index,index))
      output_list.append("temp_value_sqrd_%d += pow(o_v_%d[i].value,2);"%(index,index))
    output_list.append("}")
    
    output_list.append("//**Returning Result**")
    #output_list.append("printf(\"path_points_array[0]=%d\\n\",path_points_array[0]);")
    for index,d in enumerate(self.derivative):
      output_list.append("temp_data->thread_result[%d] = temp_total_%d;"%(index,index))
      output_list.append("temp_data->thread_result_sqrd[%d] = temp_value_sqrd_%d;"%(index,index))
    
    output_list.append("//**Cleaning up**")
    output_list.append("clReleaseKernel(%s_kernel);"%self.output_file_name)
    output_list.append("clReleaseProgram(program);")
    output_list.append("clReleaseCommandQueue(command_queue);")
    output_list.append("clReleaseContext(context);")
    output_list.append("clReleaseMemObject(path_points_buff);")
    
    for index,u in enumerate(self.underlying):
        output_list.append("clReleaseMemObject(u_a_%d_buff);" % (index))
        
    for index,d in enumerate(self.derivative):
	output_list.append("clReleaseMemObject(o_a_%d_buff);" % (index))
    
    output_list.append("}")
    
    return output_list
  
  def generate_libraries(self):
    output_list = MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.generate_libraries(self)
    
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    #print output_list
    for u in self.underlying: 
      if(not(os.path.exists("../../MulticoreCPU/multicore_c_code/%s.c"%u.name)) or not(os.path.exists("../../MulticoreCPU/multicore_c_code/%s.h"%u.name))): raise IOError, ("missing the source code for the underlying - ../../MulticoreCPU/multicore_c_code/%s.c or ../../MulticoreCPU/multicore_c_code/%s.h" % (u.name,u.name))
      else:
	output_list.remove("#include \"%s.h\";"%u.name)
	output_list.append("#include \"../../MulticoreCPU/multicore_c_code/%s.h\""%u.name)
	
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
    return output_list
  
  def generate_kernel(self):
    output_list = []
    
    #Changing to code generation directory for underlying and derivatives
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    if("AMD" in self.platform.platform_name): output_list.append("#define AMD_GPU")
    output_list.append("#define %s"%self.platform.name.upper())
    output_list.append("#include \"mwc64x.cl\"")
    #Checking that the source code for the derivative and underlying required is avaliable
    for u in self.underlying: 
      if(not(os.path.exists("%s.c"%u.name)) or not(os.path.exists("%s.h"%u.name))): raise IOError, ("missing the source code for the underlying - %s.c or %s.h" % (u.name,u.name))
      elif("#include \"%s.c\""%u.name not in output_list): output_list.append("#include \"%s.c\""%u.name) #Include source code body files as it all gets compiled at once
        
    #for d in self.derivative:
      #if(not(os.path.exists("%s.c"%d.name)) or not(os.path.exists("%s.h"%d.name))): raise IOError, ("missing the source code for the derivative - %s.c or %s.h" %  (d.name,d.name))
      #else: output_list.append("#include \"%s.c\""%d.name) #Include source code body files as it all gets compiled at once
    
    temp = []
    for d in self.derivative:
            if(not(d.name in temp)):
		if(not(os.path.exists("%s.c"%d.name)) or not(os.path.exists("%s.h"%d.name))): raise IOError, ("missing the source code for the derivative - %s.c or %s.h" %  (d.name,d.name))
                
                output_list.append("#include \"%s.c\"" % d.name)
                temp.append(d.name)
                
		base_list = []
		self.generate_base_class_names(d.__class__,base_list)
		#base_list.remove("option")
                
		for b in base_list:
		    if(b not in temp):
			if(not(os.path.exists("%s.c"%b)) or not(os.path.exists("%s.h"%b))): raise IOError, ("missing the source code for the derivative - %s.c or %s.h" %  (b,b))
			output_list.append("#include \"%s.c\"" % b)
			temp.append(b)
                    
    #Leaving code generation directory
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
    output_list.append("kernel void %s_kernel(global int *path_points,"%self.output_file_name)
    for index,u in enumerate(self.underlying):
      output_list.append("\tconstant %s_attributes *u_a_%d,"%(u.name,index))
      #output_list.append("\tlocal %s_attributes *local_u_a_%d,"%(u.name,index))
      output_list.append("\tglobal mwc64x_state_t *u_v_%d,"%(index))
      #output_list.append("\tlocal %s_variables *local_u_v_%d,"%(u.name,index))
      
    for index,d in enumerate(self.derivative):
      output_list.append("\tconstant %s_attributes *o_a_%d,"%(d.name,index))
      #output_list.append("\tlocal %s_attributes *local_o_a_%d,"%(d.name,index))
      
      output_list.append("\tglobal %s_variables *o_v_%d,"%(d.name,index))
      #output_list.append("\tlocal %s_variables *local_o_v_%d,"%(d.name,index))
      
    output_list[-1] = "%s){" % (output_list[-1][:-1])
    
    output_list.append("//**getting unique ID**")
    output_list.append("int i = get_global_id(0);")
    #output_list.append("int j = get_local_id(0);")
    output_list.append("//**reading parameters from host**")
    output_list.append("int local_path_points=path_points[0];")
    #for index,u in enumerate(self.underlying):
      #output_list.append("local_u_a_%d[0] = u_a_%d[0];"%(index,index))
      #output_list.append("temp_u_v;"%(u.name,index)) #= u_v_%d[i];"%(u.name,index,index))
      
    #for index,d in enumerate(self.derivative):
      #output_list.append("local_o_a_%d[0] = o_a_%d[0];"%(index,index))
      #output_list.append("temp_o_v;"%(d.name,index)) #= o_v_%d[i];"%(d.name,index,index))
    
    output_list.append("//**Initiating the Path and creating path variables**")
    for index,u in enumerate(self.underlying):
	output_list.append("%s_attributes temp_u_a_%d = u_a_%d[0];"%(u.name,index,index))
	output_list.append("%s_variables temp_u_v_%d;"%(u.name,index)) #= u_v_%d[j]
        
        output_list.append("%s_underlying_path_init(&temp_u_v_%d,&temp_u_a_%d);" % (u.name,index,index))
        if("AMD" in self.platform.platform_name):
          output_list.append("temp_u_v_%d.rng_state = u_v_%d[i];"%(index,index))
        
        #output_list.append("local_u_a_%d[0] = temp_u_a;"%(index))
	#output_list.append("local_u_v_%d[i] = temp_u_v;"%(index))
        
        output_list.append("double spot_price_%d = temp_u_a_%d.current_price*exp(temp_u_v_%d.gamma);"%(index,index,index))
        output_list.append("double time_%d = temp_u_v_%d.time;"%(index,index))
        
    """output_list.append("//**Initiating the Path and creating path variables**")
    for index,u in enumerate(self.underlying): 
        output_list.append("%s_underlying_path_init(&u_v_%d[i],&u_a_%d[0]);" % (u.name,index,index))
        output_list.append("double spot_price_%d = u_a_%d[i].current_price*exp(u_v_%d[i].gamma);"%(index,index,index))
        output_list.append("double time_%d = u_v_%d[i].time;"%(index,index))"""
    
    for index,d in enumerate(self.derivative):
        #output_list.append("%s_derivative_path_init(&local_o_v_%d,&local_o_a_%d);" % (d.name,index,index))
        output_list.append("%s_attributes temp_o_a_%d = o_a_%d[0];"%(d.name,index,index))
	output_list.append("%s_variables temp_o_v_%d;"%(d.name,index)) # = o_v_%d[j]
        output_list.append("%s_derivative_path_init(&temp_o_v_%d,&temp_o_a_%d);" % (d.name,index,index))
        #output_list.append("local_o_a_%d[0] = temp_o_a;"%(index))
	#output_list.append("local_o_v_%d[i] = temp_o_v;"%(index))
        
        #If a derivative doesn't have the number of path points specified, its delta time needs to be set to reflect what is the default points or that of the other derivatives
	#if("points" not in self.derivative_attributes[index]): output_list.append("local_o_v_%d.delta_time = local_o_a_%d.time_period/local_path_points;"%(index,index))
	if("points" not in self.derivative_attributes[index]): output_list.append("temp_o_v_%d.delta_time = temp_o_a_%d.time_period/local_path_points;"%(index,index))
	
    output_list.append("//**Running the path**")
    output_list.append("for(int j=0;j<local_path_points;++j){")
    
    temp_underlying = self.underlying[:]
    for index,d in enumerate(self.derivative):
      for u in d.underlying: #Calling derivative and underlying path functions
	u_index = self.underlying.index(u)
	#output_list.append("%s_derivative_path(spot_price_%d,time_%d,&local_o_v_%d,&local_o_a_%d);" % (d.name,u_index,u_index,index,index))
	#output_list.append("temp_o_a = local_o_a_%d[0];"%(index))
	#output_list.append("temp_o_v = local_o_v_%d[i];"%(index))
	output_list.append("%s_derivative_path(spot_price_%d,time_%d,&temp_o_v_%d,&temp_o_a_%d);" % (d.name,u_index,u_index,index,index))
	#output_list.append("local_o_a_%d[0] = temp_o_a;"%(index))
	#output_list.append("local_o_v_%d[i] = temp_o_v;"%(index))
	
	if(u in temp_underlying):
	  #output_list.append("%s_underlying_path(local_o_v_%d.delta_time,&local_u_v_%d,&local_u_a_%d);" % (u.name,index,u_index,u_index))
	  #output_list.append("temp_u_a = local_u_a_%d[0];"%(index))
	  #output_list.append("temp_u_v = local_u_v_%d[i];"%(index))
	  output_list.append("%s_underlying_path(temp_o_v_%d.delta_time,&temp_u_v_%d,&temp_u_a_%d);" % (u.name,index,u_index,u_index))
	  #output_list.append("local_u_a_%d[0] = temp_u_a;"%(index))
	  #output_list.append("local_u_v_%d[i] = temp_u_v;"%(index))
	  
	  temp_underlying.remove(u)
	  
	  #output_list.append("spot_price_%d = local_u_a_%d.current_price*exp(local_u_v_%d.gamma);"%(u_index,u_index,u_index))
	  #output_list.append("time_%d = local_u_v_%d.time;"%(u_index,u_index))
	  output_list.append("spot_price_%d = temp_u_a_%d.current_price*exp(temp_u_v_%d.gamma);"%(u_index,u_index,u_index))
	  output_list.append("time_%d = temp_u_v_%d.time;"%(u_index,u_index))
    
    output_list.append("}") #End of For Loop
    
    output_list.append("//**Calculating payoff(s) and returning the result**")
    for index,d in enumerate(self.derivative):
      for u in d.underlying:
	u_index = self.underlying.index(u)
	#output_list.append("temp_o_a = local_o_a_%d[0];"%(index))
	#output_list.append("temp_o_v = local_o_v_%d[i];"%(index))
	output_list.append("%s_derivative_payoff(spot_price_%d,&temp_o_v_%d,&temp_o_a_%d);"%(d.name,u_index,index,index))
	output_list.append("o_v_%d[i] = temp_o_v_%d;"%(index,index))
	#output_list.append("%s_derivative_payoff(spot_price_%d,&local_o_v_%d,&local_o_a_%d);"%(d.name,u_index,index,index))
	#output_list.append("o_v_%d[i] = local_o_v_%d[j];"%(index,index))
	
    
    output_list.append("}") #End of Kernel
    
    #Turning output list into output string
    output_string = output_list[0]
    for line in output_list[1:]: output_string = "%s\n%s"%(output_string,line)
    output_string = "%s\n"%(output_string) #Adding newline to end of file
    self.kernel_code_string = output_string
    
    return output_list
      
  def generate_cpu_seed_kernel(self):
    output_list = []
    
    #Changing to code generation directory for underlying and derivatives
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    output_list.append("#define %s"%self.platform.name.upper())
    output_list.append("#include \"mwc64x.cl\"")
    #Checking that the source code for the derivative and underlying required is avaliable
    for u in self.underlying: 
      if(not(os.path.exists("%s.c"%u.name)) or not(os.path.exists("%s.h"%u.name))): raise IOError, ("missing the source code for the underlying - %s.c or %s.h" % (u.name,u.name))
      elif("#include \"%s.c\""%u.name not in output_list): output_list.append("#include \"%s.c\""%u.name) #Include source code body files as it all gets compiled at once
                        
    #Leaving code generation directory
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
    output_list.append("kernel void %s_cpu_seed_kernel("%self.output_file_name)
    for index,u in enumerate(self.underlying):
      output_list.append("\tlocal mwc64x_state_t *local_u_v_%d,"%(index))
      output_list.append("\tglobal mwc64x_state_t *u_v_%d,"%(index))
      
    output_list[-1] = "%s){" % (output_list[-1][:-1])
    
    output_list.append("//**getting unique ID**")
    output_list.append("int i = get_global_id(0);")
    output_list.append("int j = get_local_id(0);")
    
    output_list.append("//**Initiating the Path for each underlying**")
    for index,u in enumerate(self.underlying):
	output_list.append("mwc64x_state_t temp_u_v_%d;"%(index))
        output_list.append("if(j==0){")
        output_list.append("MWC64X_SeedStreams(&(temp_u_v_%d),0,4096*2);"%index)
        output_list.append("local_u_v_%d[j] = temp_u_v_%d;"%(index,index))
        output_list.append("}")
        output_list.append("barrier(CLK_LOCAL_MEM_FENCE);")
        output_list.append("if(j>0){")
        output_list.append("temp_u_v_%d=local_u_v_%d[0];"%(index,index))
        output_list.append("MWC64X_Skip( &(temp_u_v_%d), 4096*2);"%index)
        output_list.append("}")
        output_list.append("u_v_%d[i] = temp_u_v_%d;"%(index,index))
        
    output_list.append("}") #End of Kernel
    
    #Turning output list into output string
    output_string = output_list[0]
    for line in output_list[1:]: output_string = "%s\n%s"%(output_string,line)
    output_string = "%s\n"%(output_string) #Adding newline to end of file
    self.cpu_seed_kernel_code_string = output_string
    
    return output_list
  
  
  def compile(self,override=True,cleanup=True,debug=False):
    
    compile_flags = ["-lOpenCL","-I/opt/AMDAPP/include","-fpermissive"]
    if(debug): compile_flags.append("-ggdb")
    if('Darwin' in plat.system()):
      compile_flags.remove("-lOpenCL")
      compile_flags.append("-framework")
      compile_flags.append("OpenCL")
    result = MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.compile(self,override,compile_flags,debug) #Compiling Host C Code
      
    os.chdir("..")
    os.chdir(self.platform.platform_directory())
    
    path_string = "mwc64x/cl"
    if('Darwin' in plat.system()): path_string = "%s/%s"%(os.getcwd(),path_string)
    
    self.program = pyopencl.Program(self.platform.context,self.kernel_code_string).build(["-I . -I %s"%path_string]) #Creating OpenCL program based upon Kernel
    binary_kernel = self.program.get_info(pyopencl.program_info.BINARIES)[0] #Getting the binary code for the OpenCL code
    binary_kernel_file = open("%s.clbin"%self.output_file_name,"w") #Writing the binary code to a file to be read by the Host C Code
    binary_kernel_file.write(binary_kernel)
    binary_kernel_file.close()
    
    #If using an AMD Platform, Compile OpenCL Kernel Code for seeding using the Host CPU
    if("AMD" in self.platform.platform_name):
      self.cpu_seed_program = pyopencl.Program(self.platform.cpu_context,self.cpu_seed_kernel_code_string).build(["-I . -I %s"%path_string]) #Creating OpenCL program based upon Kernel
      binary_kernel = self.cpu_seed_program.get_info(pyopencl.program_info.BINARIES)[0] #Getting the binary code for the OpenCL code
      binary_kernel_file = open("%s_cpu_seed.clbin"%self.output_file_name,"w") #Writing the binary code to a file to be read by the Host C Code
      binary_kernel_file.write(binary_kernel)
      binary_kernel_file.close()
    
    os.chdir(self.platform.root_directory())
    os.chdir("bin")
    
      
    return result
  
 