'''
Created on 23 February 2013

'''
import os,time,subprocess,sys,time,math,pyopencl
from ForwardFinancialFramework.Platforms.MulticoreCPU import MulticoreCPU_MonteCarlo
from ForwardFinancialFramework.Platforms.OpenCLGPU import OpenCLGPU
from ForwardFinancialFramework.Solvers.MonteCarlo import MonteCarlo

class OpenCLGPU_MonteCarlo(MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo):
	"""OpenCL GPU Monte Carlo Solver class

	This class provides the generation, compilation and execution behaviours for OpenCL GPU platforms (including Xeon Phis if the OpenCL device type is set to ACCELERATOR).
	The Multicore solver class is reused heavily, with only the activity thread being implemented differently.
	"""
	def __init__(self,derivative,paths,platform,default_points=4096,reduce_underlyings=True,kernel_path_max=8,random_number_generator="mwc64x_boxmuller",floating_point_format="float",runtime_opencl_compile=None):
    		MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.__init__(self,derivative,paths,platform,reduce_underlyings,default_points=default_points,random_number_generator=random_number_generator,floating_point_format=floating_point_format)
    		"""Constructor
		
		Parameters
			derivative, paths, platform, reduce_underlyings, default_points, random_number_generator, floating_point_format - same as in MulticoreCPU_MonteCarlo class
			kernel_path_max - (int) number of simulations to perform within each workitem
			runtime_opencl_compile - (bool) option for performing OpenCL compile at runtime as opposed to when compiling host code. Defaults to False on Linux, and True on Mac OSx
		"""
		self.solver_metadata["threads"] = 1 #In this context this means something different
    
    		#Forcing the RNG to be the Taus Boxmuller
		if(("Advanced Micro Devices" in self.platform.platform_name or "AMD" in self.platform.platform_name or "Intel" in self.platform.platform_name) and (self.random_number_generator=="mwc64x_boxmuller")): self.random_number_generator = "taus_boxmuller"
   
   		#flag for check if OSX or not
		if(runtime_opencl_compile==None and "darwin" in sys.platform): self.runtime_opencl_compile = True
		elif(runtime_opencl_compile==None): self.runtime_opencl_compile = False
		else: self.runtime_opencl_compile = runtime_opencl_compile

    		if("darwin" in sys.platform):
      			self.utility_libraries.extend(["OpenCL/opencl.h"])
      			#mwc64x_path_string = "%s/../%s/%s"%(os.getcwd(),self.platform.platform_directory(),mwc64x_path_string)
    		else:
      			self.utility_libraries += ["CL/opencl.h"]
      
      		#Asserts are used to make OpenCL errors runtime errors
    		self.utility_libraries.append("assert.h")
    
    		for u in self.underlying:
      			if((self.random_number_generator=="taus_boxmuller" or self.random_number_generator=="taus_ziggurat")):
				self.utility_libraries.append("gauss.h")
				break

		self.activity_thread_name = "opencl_montecarlo_activity_thread"

		self.kernel_code_string = ""
		self.cpu_seed_kernel_code_string = ""

		self.floating_point_format = "float"

		#Setting the number of points in the path, as determined by the derivatives passed to the solver
		#TODO where must this go? Probably somewhere that it will get called everytime the generate command is called
		path_points = 0

		for index,d in enumerate(self.derivative):
      			if("points" in self.derivative_attributes[index]):
				if((d.points!=path_points) and path_points): raise IOError, ("For an OpenCL solver the number of path points must match")
				elif(not(path_points)): path_points = d.points
	
		if(path_points): self.solver_metadata["path_points"] = path_points
    		else: self.solver_metadata["path_points"] = self.solver_metadata["default_points"]
    
    		self.solver_metadata["kernel_loops"] = kernel_path_max
    		self.kernel_loops = self.solver_metadata["kernel_loops"]
    
    		self.solver_metadata["work_groups_per_compute_unit"] = 1
    
    		self.solver_metadata["gpu_threads"] = 0
    
    		self.header_string = "//%s.c Generated by Monte Carlo OpenCL Solver"%self.output_file_name
  
  
	def generate(self,override=True,verbose=False,debug=False):
   	 	"""Generate solver method

		In addition to calling the Multicore CPU solver class to generate the host code, the kernel code is also generated.

		Parameters
			override, verbose, debug - same as in MulticoreCPU_MonteCarlo class
		"""
		#Generate OpenCL Kernel Code
    		self.kernel_code_list = self.generate_kernel()
    		self.generate_source(self.kernel_code_list,".cl")
    
    		#Generate C Host Code largely using Multicore C infrastructure
    		MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.generate(self,".c",override,verbose,debug)
    
 
	def generate_kernel_binary_file_read(self,file_extension="clbin"):
		"""Helper method for generating code for reading the size and contents of a kernel binary file.

		Parameters
			file_extenions - (str) file extension of kernel binary file
		"""
		output_list = []
		output_list.append("size_t binary_size;")
		output_list.append("FILE *fp = fopen(\"%s/%s.%s\", \"r\");"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name,file_extension))
		output_list.append("assert(fp != NULL);")
		output_list.append("fseek(fp,0,SEEK_END);")
		output_list.append("binary_size = ftell(fp);")
		output_list.append("fseek(fp,0,SEEK_SET);")

		output_list.append("char *binary_buf = (char *)malloc(binary_size+1);")
		output_list.append("size_t read_size = fread(binary_buf, sizeof(char), binary_size, fp);")
		output_list.append("assert(read_size == binary_size);")
		output_list.append("fclose(fp);")
		
		return output_list

	def generate_opencl_kernel_call(self,first_call=False,runtime_managed_wg_sizes=False,dep_events_str=None,dep_events_num=None):
		if(first_call and dep_events_str==None): 
			dep_events_str = "NULL"
			dep_events_num = 0
		elif(dep_events_str==None):
			dep_events_str = "read_events"
			dep_events_num = len(self.derivative*2)
		
		wg_str = "&local_kernel_paths"
		if(runtime_managed_wg_sizes): wg_str = "NULL"

		output_list = []
		output_list.append("ret = clEnqueueNDRangeKernel(command_queue, %s_kernel, (cl_uint) 1, NULL, &kernel_paths, %s, %d, %s, kernel_event);"%(self.output_file_name,wg_str,dep_events_num,dep_events_str))

		return output_list

	def generate_kernel_runtime_parameters(self):
		output_list = []

   		output_list.append("size_t pref_wg_size_multiple;")
		output_list.append("ret = clGetKernelWorkGroupInfo(%s_kernel,device,CL_KERNEL_PREFERRED_WORK_GROUP_SIZE_MULTIPLE,sizeof(size_t),&pref_wg_size_multiple,NULL);"%self.output_file_name)
    		output_list.append("assert(ret==CL_SUCCESS);")
    
    		output_list.append("size_t max_wg_size;")
    		output_list.append("ret = clGetKernelWorkGroupInfo(%s_kernel,device,CL_KERNEL_WORK_GROUP_SIZE,sizeof(size_t),&max_wg_size,NULL);"%self.output_file_name)
    		output_list.append("assert(ret==CL_SUCCESS);")
    
		output_list.append("cl_uint compute_units;")
		output_list.append("ret = clGetDeviceInfo(device,CL_DEVICE_MAX_COMPUTE_UNITS,sizeof(cl_uint),&compute_units,NULL);")
		output_list.append("assert(ret==CL_SUCCESS);")

		output_list.append("size_t local_work_items = max_wg_size;")
		output_list.append("size_t chunk_paths = local_work_items*compute_units*work_groups_per_compute_unit;")

		#This is if the number of paths specified is below the optimal execution parameters
		output_list.append("local_work_items = (local_work_items < temp_data->thread_paths) ? local_work_items : pref_wg_size_multiple;")
		output_list.append("chunk_paths = (chunk_paths < temp_data->thread_paths) ? chunk_paths - chunk_paths%local_work_items : temp_data->thread_paths - temp_data->thread_paths%local_work_items;")
    
		#This allows overriding of the number of compute units being used, which are the unit of task parallelism in OpenCL
		output_list.append("if(gpu_threads) chunk_paths = (chunk_paths/local_work_items < gpu_threads) ? chunk_paths : gpu_threads*local_work_items;")    
		
		output_list.append("const size_t kernel_paths = chunk_paths;")
		output_list.append("const size_t local_kernel_paths = local_work_items;")
		output_list.append("unsigned int chunks = ceil(((FP_t)temp_data->thread_paths)/chunk_paths/kernel_loops);")
		
		return output_list
	
	def generate_attribute_structures(self):
		output_list = []

		for index,u in enumerate(self.underlying): output_list.append("%s_attributes u_a_%d;" % (u.name,index))
        	for index,d in enumerate(self.derivative): output_list.append("%s_attributes o_a_%d;" % (d.name,index))

		return output_list

	def generate_attribute_kernel_arguments(self,offset=5):
		output_list = []

		for index,u in enumerate(self.underlying):
			output_list.append("ret = clSetKernelArg(%s_kernel, %d, sizeof(%s_attributes), &u_a_%d);"%(self.output_file_name,offset + index, u.name, index))
      			output_list.append("assert(ret==CL_SUCCESS);")

		for index,d in enumerate(self.derivative):
		      	output_list.append("ret = clSetKernelArg(%s_kernel, %d, sizeof(%s_attributes), &o_a_%d);"%(self.output_file_name,offset + len(self.underlying) + index, d.name, index))
		      	output_list.append("assert(ret==CL_SUCCESS);")

		return output_list

	def generate_activity_thread(self,debug=False):
    		"""Helper method for generating activity thread

		Overrides the method in MulticoreCPU_MonteCarlo
		"""
		output_list = []

		output_list.append("//*MC OpenCL Activity Thread Function*")
		output_list.append("void * %s(void* thread_arg){"%self.activity_thread_name)
		output_list.append("struct thread_data* temp_data;")
		output_list.append("temp_data = (struct thread_data*) thread_arg;")
        
		#Declaring OpenCL Data Structures
		output_list.append("//**Creating OpenCL Infrastructure**")
		output_list.append("cl_int ret;")

		#Creating OpenCL Platform
		#TODO Use PyOpenCL to find this information out
		output_list.append("//***Creating Platform***")
		output_list.append("cl_uint num_platforms;");
		output_list.append("clGetPlatformIDs(0, NULL, &num_platforms);")
		output_list.append("cl_platform_id* platform_id = (cl_platform_id*)malloc(sizeof(cl_platform_id) * num_platforms);")
		output_list.append("cl_platform_id platform = NULL;")
		output_list.append("clGetPlatformIDs(num_platforms, platform_id, &num_platforms);")
		output_list.append("for(unsigned int i = 0; i < num_platforms; ++i){")
		output_list.append("char pbuff[100];")
		output_list.append("ret = clGetPlatformInfo(platform_id[i],CL_PLATFORM_VENDOR,sizeof(pbuff),pbuff,NULL);")
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("platform = platform_id[i];")
		output_list.append("if(!strcmp(pbuff, \"%s\")){break;}"%(self.platform.platform_name))
		output_list.append("}")

		#Creating OpenCL Context
		output_list.append("//***Creating Context***")
		output_list.append("cl_context_properties cps[3] = { CL_CONTEXT_PLATFORM, (cl_context_properties)platform, 0 };")
		output_list.append("cl_context context = clCreateContextFromType(cps, CL_DEVICE_TYPE_%s, NULL, NULL, &ret);"%pyopencl.device_type.to_string(self.platform.device_type))
		output_list.append("assert(ret==CL_SUCCESS);")
     
		#Creating OpenCL Device
		output_list.append("//***Creating Device***")
		output_list.append("size_t deviceListSize;")
		output_list.append("ret = clGetContextInfo(context,CL_CONTEXT_DEVICES,0, NULL,&deviceListSize);")
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("cl_device_id *devices = (cl_device_id *)malloc(deviceListSize);")
		output_list.append("ret = clGetContextInfo(context, CL_CONTEXT_DEVICES, deviceListSize,devices,NULL);")
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("cl_device_id device = devices[0];")
     
		#Creating the OpenCL Program from the precompiled binary
		if(not self.runtime_opencl_compile):
			output_list.append("//***Creating Program***")
			output_list.extend(self.generate_kernel_binary_file_read())
			output_list.append("cl_program program = clCreateProgramWithBinary(context, 1, &device, (const size_t *)&binary_size,(const unsigned char **)&binary_buf, NULL, &ret);")
			output_list.append("assert(ret==CL_SUCCESS);")
			output_list.append("ret = clBuildProgram(program, 1, &device, NULL, NULL, NULL);")
			#output_list.append("printf(\"%d\\n\",ret==CL_INVALID_PROGRAM);")
			output_list.append("assert(ret==CL_SUCCESS);")
      
      
    		else: #The Apple OpenCL implementation doesn't seem to support binary precompilation for some reason
			output_list.append("FILE *fp;")
		      	output_list.append("char *source_str;")
		      	output_list.append("size_t source_size;")
		      	output_list.append("fp=fopen(\"%s/%s.cl\",\"r\");"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name))
		      	output_list.append("source_str = (char *)malloc(0x100000);")
		      	output_list.append("source_size = fread(source_str, 1, 0x100000, fp);")
		      	output_list.append("fclose(fp);")
		      	output_list.append("cl_program program = clCreateProgramWithSource(context, 1, (const char **)&source_str, (const size_t *)&source_size, &ret);")
		      	output_list.append("assert(ret==CL_SUCCESS);")
      
      
     		opencl_compile_flags = "-DOPENCL_GPU"
      
      		if(self.random_number_generator=="mwc64x_boxmuller"):
			opencl_compile_flags += " -DMWC64X_BOXMULLER"
	
		elif(self.random_number_generator=="taus_boxmuller" or self.random_number_generator=="taus_ziggurat"):
			opencl_compile_flags += " -DTAUS_BOXMULLER"
      
      		output_list.append("const char* buildOption =\"%s\";"%opencl_compile_flags) #-x clc++
      		output_list.append("ret = clBuildProgram(program, 1, &device, buildOption, NULL, NULL);")
      
      		#Outputing the Build Log
		if(debug):
      			output_list.append("size_t ret_val_size;")
      			output_list.append("clGetProgramBuildInfo(program, device, CL_PROGRAM_BUILD_LOG, 0, NULL, &ret_val_size);")   
      			output_list.append("char build_log[ret_val_size+1];")
      			output_list.append("clGetProgramBuildInfo(program,device,CL_PROGRAM_BUILD_LOG,sizeof(build_log),build_log,NULL);")
      			output_list.append("build_log[ret_val_size] = '\0';")
      			output_list.append("printf(\"OpenCL Build Log: %s\\n\",build_log);")
      
      		output_list.append("assert(ret==CL_SUCCESS);") #We want to see the build log even if the build program command fails

    		#Creating the OpenCL Kernel
    		output_list.append("//***Creating Kernel Object***")
    		output_list.append("cl_kernel %s_kernel = clCreateKernel(program,\"%s_kernel\",&ret);"%(self.output_file_name,self.output_file_name))
    		output_list.append("assert(ret==CL_SUCCESS);")
    
    		#Optimising kernel execution parameters
    		output_list.append("//***Optimising Kernel Parameters***")
    
		output_list.extend(self.generate_kernel_runtime_parameters())
      
		##Creating the Command Queue for the Kernel
    		output_list.append("//**Creating OpenCL Command Queue**")
    		output_list.append("cl_command_queue command_queue = clCreateCommandQueue(context, device, 0, &ret);")
    		output_list.append("assert(ret==CL_SUCCESS);") 
		
		#Creating the Memory Objects for each underlying and derivative
		output_list.append("//***Creating OpenCL Memory Objects***")
    
		#Adding attribute memory structures
		output_list.extend(self.generate_attribute_structures())
    		
		#Derivative value memory structures
		for index,d in enumerate(self.derivative):
       			output_list.append("FP_t *value_%d;"%index)
			output_list.append("ret = posix_memalign((void**)&value_%d, 64, chunk_paths*sizeof(FP_t));" % index) 
        		output_list.append("assert(ret==0);")
			output_list.append("cl_mem value_%d_buff = clCreateBuffer(context, CL_MEM_WRITE_ONLY,chunk_paths*sizeof(FP_t),NULL,&ret);" % (index))
			output_list.append("assert(ret==CL_SUCCESS);")
        		
			output_list.append("FP_t *value_sqrd_%d;" % index)
			output_list.append("ret = posix_memalign((void**)&value_sqrd_%d, 64, chunk_paths*sizeof(FP_t));" % index) 
        		output_list.append("assert(ret==0);")
        		output_list.append("cl_mem value_sqrd_%d_buff = clCreateBuffer(context, CL_MEM_WRITE_ONLY,chunk_paths*sizeof(FP_t),NULL,&ret);" % (index))
			output_list.append("assert(ret==CL_SUCCESS);")
    		
        
    		output_list.append("//**Setting Kernel Arguments**")
		
		#Binding the Memory Objects to the Kernel
		output_list.append("//**Setting Kernel Arguments**")
		output_list.append("ret = clSetKernelArg(%s_kernel, 0, sizeof(cl_uint), &path_points);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("cl_uint seed = (cl_uint) (temp_data->thread_rng_seed);")
		output_list.append("ret = clSetKernelArg(%s_kernel, 1, sizeof(cl_uint), &seed);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("cl_uint chunk_size = chunk_paths*kernel_loops;")
		output_list.append("ret = clSetKernelArg(%s_kernel, 2, sizeof(cl_uint), &chunk_size);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("cl_uint chunk_number = 0;")
		output_list.append("ret = clSetKernelArg(%s_kernel, 3, sizeof(cl_uint), &chunk_number);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")
		output_list.append("ret = clSetKernelArg(%s_kernel, 4, sizeof(cl_uint), &kernel_loops);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")
    		
		for index,u in enumerate(self.underlying):
      			temp = ("%s_underlying_init("%u.name)
      			for u_a in self.underlying_attributes[index][:-1]: temp=("%s%s_%d_%s,"%(temp,u.name,index,u_a))
      			temp=("%s%s_%d_%s,&u_a_%d);"%(temp,u.name,index,self.underlying_attributes[index][-1],index))   
      			output_list.append(temp)	
       
    		for index,d in enumerate(self.derivative):
      			temp = ("%s_derivative_init("%d.name)
      			for o_a in self.derivative_attributes[index][:-1]: temp=("%s%s_%d_%s,"%(temp,d.name,index,o_a))
      			temp=("%s%s_%d_%s,&o_a_%d);"%(temp,d.name,index,self.derivative_attributes[index][-1],index))
		      	output_list.append(temp)

		
		#Setting attribute structure arguments
		output_list.extend(self.generate_attribute_kernel_arguments())
    
		for index,d in enumerate(self.derivative):
		      	output_list.append("ret = clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&value_%d_buff);"%(self.output_file_name,5 + len(self.underlying) + len(self.derivative) + index*2,index))
		      	output_list.append("assert(ret==CL_SUCCESS);")
		      	
			output_list.append("ret = clSetKernelArg(%s_kernel, %d, sizeof(cl_mem), (void *)&value_sqrd_%d_buff);"%(self.output_file_name,5 + len(self.underlying) + len(self.derivative) + index*2 + 1,index))
		      	output_list.append("assert(ret==CL_SUCCESS);")
				
    
   		for d in range(len(self.derivative)): 
      			output_list.append("long double temp_total_%d = 0;"%d)
      			output_list.append("long double temp_value_sqrd_%d = 0;"%d)
      
		#Running the actual kernel for the first time
		output_list.append("//**Run the kernel for the 1st Time**")
		output_list.append("cl_event kernel_event[1];")
		output_list.append("cl_event read_events[%d];"%(len(self.derivative)*2))
		
		output_list.extend(self.generate_opencl_kernel_call(first_call=True))
		#output_list.append("ret = clEnqueueNDRangeKernel(command_queue, %s_kernel, (cl_uint) 1, NULL, &kernel_paths, &local_kernel_paths, 0, NULL, kernel_event);"%(self.output_file_name))
		output_list.append("assert(ret==CL_SUCCESS);")    
    		output_list.append("unsigned int j = 1;")
    		for index,d in enumerate(self.derivative): output_list.append("long long remaining_paths_%d = temp_data->thread_paths;"%index)
      
    		output_list.append("while(")
 		for index,d in enumerate(self.derivative): output_list.append("remaining_paths_%d>0 &&"%index)
    		output_list.append("1){")
    		output_list.append("chunk_number = j;")
    
    		#Reading the Results out
    		output_list.append("//**Reading the results**")
    		for d_index,d in enumerate(self.derivative):
        		output_list.append("ret = clEnqueueReadBuffer(command_queue, value_%d_buff, CL_TRUE, 0, chunk_paths * sizeof(FP_t),value_%d, 1, kernel_event, &read_events[%d]);"%(d_index,d_index,d_index*2))
        		output_list.append("assert(ret==CL_SUCCESS);")
			output_list.append("ret = clEnqueueReadBuffer(command_queue, value_sqrd_%d_buff, CL_TRUE, 0, chunk_paths * sizeof(FP_t),value_sqrd_%d, 1, kernel_event, &read_events[%d]);"%(d_index,d_index,d_index*2+1))
			output_list.append("assert(ret==CL_SUCCESS);")
    
    		output_list.append("ret = clSetKernelArg(%s_kernel, 3, sizeof(cl_uint), &chunk_number);"%(self.output_file_name))
    		output_list.append("assert(ret==CL_SUCCESS);")
    
    		#Running the actual kernel
    		output_list.append("//**Run the kernel**")
		output_list.extend(self.generate_opencl_kernel_call(first_call=True))
    		output_list.append("assert(ret==CL_SUCCESS);")
    
   		output_list.append("//**Post-Kernel Calculations**")
    		output_list.append("for(int i=0;i<chunk_paths;i++){")
    		for index,d in enumerate(self.derivative):
      			output_list.append("if((remaining_paths_%d>0) && !(isnan(value_%d[i])||isinf(value_%d[i]))){"%(index,index,index))
      			output_list.append("temp_total_%d += value_%d[i];"%(index,index))
      			output_list.append("temp_value_sqrd_%d += value_sqrd_%d[i];"%(index,index))
      			output_list.append("remaining_paths_%d = remaining_paths_%d - kernel_loops;"%(index,index))
      			output_list.append("}")
    		output_list.append("}")
    
    		output_list.append("j++;")
    		output_list.append("}")
    		output_list.append("ret = clFinish(command_queue);")
    		output_list.append("assert(ret==CL_SUCCESS);")
    
    		output_list.append("//**Returning Result**")
    
    		for index,d in enumerate(self.derivative):
      			output_list.append("temp_data->thread_result[%d] = temp_total_%d;"%(index,index)) #*scaling_factor
      			output_list.append("temp_data->thread_result_sqrd[%d] = temp_value_sqrd_%d;"%(index,index)) #*scaling_factor
    
    		output_list.append("//**Cleaning up**")
    		output_list.append("ret = clReleaseEvent(*kernel_event);")
    		output_list.append("assert(ret==CL_SUCCESS);")
    
    		for index,d in enumerate(self.derivative):
      			output_list.append("ret = clReleaseEvent(read_events[%d]);"%index)
      			output_list.append("assert(ret==CL_SUCCESS);")
    
    		output_list.append("ret = clReleaseKernel(%s_kernel);"%self.output_file_name)
    		output_list.append("assert(ret==CL_SUCCESS);")
    		output_list.append("ret = clReleaseProgram(program);")
    		output_list.append("assert(ret==CL_SUCCESS);")
    		output_list.append("ret = clReleaseCommandQueue(command_queue);")
    		output_list.append("assert(ret==CL_SUCCESS);")
    		output_list.append("ret = clReleaseContext(context);")
    		output_list.append("assert(ret==CL_SUCCESS);")
        
    		for index,d in enumerate(self.derivative):
        		output_list.append("clReleaseMemObject(value_%d_buff);" % (index))
        		output_list.append("clReleaseMemObject(value_sqrd_%d_buff);" % (index))
    
    		output_list.append("}")
    
    		return output_list
  
 	def generate_kernel_attribute_arguments(self):
		output_list = []
		
		for index,u in enumerate(self.underlying):
     			output_list.append("\tconst %s_attributes u_a_%d,"%(u.name,index)) #constant
      
		for index,d in enumerate(self.derivative):
      			output_list.append("\tconst %s_attributes o_a_%d,"%(d.name,index)) #constant

		return output_list

	def generate_kernel_preprocessor_defines(self):
     		output_list = []

		#Initial defines
    		output_list.append("#ifndef M_PI")
    		output_list.append("#define M_PI 3.141592653589793238f")
    		output_list.append("#endif")
    
    		output_list.append("#define FP_t %s"%self.floating_point_format)
    		if(self.floating_point_format.lower()=="double"):
			output_list.append("#if defined(cl_amd_fp64)")
      			output_list.append("#pragma OPENCL EXTENSION cl_amd_fp64 : enable")
      			output_list.append("#elif defined(cl_khr_fp64)")
      			output_list.append("#pragma OPENCL EXTENSION cl_khr_fp64 : enable")
      			output_list.append("#endif")
      
      		#Including the RNG source file
    		path_string = ""
    		if(self.random_number_generator=="mwc64x_boxmuller"): path_string = "%s/mwc64x/cl/mwc64x.cl"%os.path.join(self.platform.root_directory(),self.platform.platform_directory())
    		elif(self.random_number_generator=="taus_boxmuller" or self.random_number_generator=="taus_ziggurat"): path_string = "%s/gauss.c"%os.path.join(self.platform.root_directory(),self.platform.platform_directory())
    		output_list.append("#include \"%s\""%path_string)
    
		#Checking that the source code for the derivative and underlying required is avaliable
    		for u in self.underlying: 
      			if("#include \"%s/%s.c\""%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),u.name) not in output_list): output_list.append("#include \"%s/%s.c\""%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),u.name)) #Include source code body files as it all gets compiled at once
        
    
   		temp = []
    		for d in self.derivative:
            		if(not(d.name in temp)): 
               			output_list.append("#include \"%s/%s.c\"" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),d.name))
                		temp.append(d.name)
                
		base_list = []
		self.generate_base_class_names(d.__class__,base_list)
                
		for b in base_list:
			if(b not in temp):
				output_list.append("#include \"%s/%s.c\"" % (os.path.join(self.platform.root_directory(),self.platform.platform_directory()),b))
				temp.append(b)
		
		return output_list


	def generate_kernel_definition(self,restrict_arrays=False):
		restrict_str = ""
		if(restrict_arrays): restrict_str = "restrict"

		output_list = []

		#Kernel definition
    		output_list.append("kernel void %s_kernel("%self.output_file_name)
    		output_list.append("\tconst uint path_points,")
    		output_list.append("\tconst uint seed,")
    		output_list.append("\tconst uint chunk_size,") #constant
    		output_list.append("\tconst uint chunk_number,") #constant
    		output_list.append("\tconst uint kernel_loops,") #constant
    
		output_list.extend(self.generate_kernel_attribute_arguments())
    		
		for index,d in enumerate(self.derivative):
      			output_list.append("\tglobal FP_t *%s value_%d,"%(restrict_str,index))
      			output_list.append("\tglobal FP_t *%s value_sqrd_%d,"%(restrict_str,index))

		output_list[-1] = "%s){" % (output_list[-1][:-1])


		return output_list

	def generate_kernel_local_memory_structures(self):
		output_list = []

    		output_list.append("//**Creating Kernel variables and Copying parameters from host**")
    		for index,u in enumerate(self.underlying):
      			output_list.append("%s_attributes temp_u_a_%d = u_a_%d;"%(u.name,index,index))
      			output_list.append("%s_variables temp_u_v_%d;"%(u.name,index))
    
    
    		for index,d in enumerate(self.derivative):
      			output_list.append("%s_attributes temp_o_a_%d = o_a_%d;"%(d.name,index,index))
      			output_list.append("%s_variables temp_o_v_%d;"%(d.name,index))

		return output_list

	def generate_kernel_path_loop_definition(self):
		output_list = []
		
		output_list.append("for(uint k=0;k<local_kernel_loops;++k){")
		
		return output_list

	def generate_kernel_rng_seeding(self):
		output_list = []

    		output_list.append("//**Creating Kernel variables and Copying parameters from host**")
    		for index,u in enumerate(self.underlying):
      			if(self.random_number_generator=="mwc64x_boxmuller"):
				if("heston_underlying" in u.name or "black_scholes_underlying" in u.name):
	  				output_list.append("MWC64X_SeedStreams(&(temp_u_v_%d.rng_state),local_seed + 4096*2*local_chunk_size*(local_chunk_number*%d + %d),4096*2);"%(index,len(self.underlying),index))
	  
      			elif(self.random_number_generator=="taus_boxmuller" or self.random_number_generator=="taus_ziggurat"):
				if("heston_underlying" in u.name or "black_scholes_underlying" in u.name):
					output_list.append("ctrng_seed(20,local_seed + %d * (i*%d+local_chunk_size*local_chunk_number),&(temp_u_v_%d.rng_state));"%(index+1,self.kernel_loops,index))

		return output_list
	
	def generate_kernel_path_points_loop_definition(self):
		output_list = []
		
		output_list.append("for(uint j=0;j<local_path_points;++j){")
		
		return output_list

	def generate_kernel(self):
 		"""Helper method for generating OpenCL kernel
		"""
	  	output_list = []
     
     		#Kernel Preprocessor commands
            	output_list.extend(self.generate_kernel_preprocessor_defines())
 
 		#Kernel definition
 		output_list.extend(self.generate_kernel_definition())

    		#Getting kernel ID
    		output_list.append("//**getting unique ID**")
    		output_list.append("int i = get_global_id(0);")
    
    		#Getting private versions of commonly used parameters
    		output_list.append("//**reading parameters from host**")
    		output_list.append("uint local_path_points = path_points;")
    		output_list.append("uint local_chunk_size = chunk_size;")
    		output_list.append("uint local_chunk_number = chunk_number;")
    		output_list.append("uint local_seed = seed;")
    		output_list.append("uint local_kernel_loops = kernel_loops;")
     
		output_list.extend(self.generate_kernel_local_memory_structures())

		for index,u in enumerate(self.underlying):
     			output_list.append("FP_t spot_price_%d,time_%d;"%(index,index))
     		
		for index,d in enumerate(self.derivative):
      			output_list.append("FP_t temp_value_%d = 0.0;"%index)
      			output_list.append("FP_t temp_value_sqrd_%d = 0.0;"%index)
    
    		#For loop for controlling the paths done per work item
   		output_list.extend(self.generate_kernel_path_loop_definition())

		output_list.extend(self.generate_kernel_rng_seeding())

		output_list.append("//**Initiating the Path and creating path variables**")
    		for index,u in enumerate(self.underlying):
        		output_list.append("%s_underlying_path_init(&temp_u_v_%d,&temp_u_a_%d);" % (u.name,index,index))
        		output_list.append("spot_price_%d = temp_u_a_%d.current_price*native_exp(temp_u_v_%d.gamma);"%(index,index,index))
        		output_list.append("time_%d = temp_u_v_%d.time;"%(index,index))
    
    		for index,d in enumerate(self.derivative):
        		output_list.append("%s_derivative_path_init(&temp_o_v_%d,&temp_o_a_%d);" % (d.name,index,index))
        
        		#If a derivative doesn't have the number of path points specified, its delta time needs to be set to reflect what is the default points or that of the other derivatives
			if("points" not in self.derivative_attributes[index]): output_list.append("temp_o_v_%d.delta_time = temp_o_a_%d.time_period/local_path_points;"%(index,index))
	
    		output_list.append("//**Running the path**")
    		output_list.extend(self.generate_kernel_path_points_loop_definition())
    
    		temp_underlying = self.underlying[:]
    		for index,d in enumerate(self.derivative):
      			for u_index,u in enumerate(d.underlying): #Calling derivative and underlying path functions
				output_list.append("%s_derivative_path(spot_price_%d,time_%d,&temp_o_v_%d,&temp_o_a_%d);" % (d.name,u_index,u_index,index,index))
	
				if(u in temp_underlying):
	  				output_list.append("%s_underlying_path(temp_o_v_%d.delta_time,&temp_u_v_%d,&temp_u_a_%d);" % (u.name,index,u_index,u_index))
	  				temp_underlying.remove(u)
	  				output_list.append("spot_price_%d = temp_u_a_%d.current_price*native_exp(temp_u_v_%d.gamma);"%(u_index,u_index,u_index))
	  				output_list.append("time_%d = temp_u_v_%d.time;"%(u_index,u_index))
    
    		output_list.append("}") #End of Path For Loop
    
    		output_list.append("//**Calculating payoff(s)**")
    		for index,d in enumerate(self.derivative):
      			for u_index,u in enumerate(d.underlying):
				output_list.append("%s_derivative_payoff(spot_price_%d,&temp_o_v_%d,&temp_o_a_%d);"%(d.name,u_index,index,index))
				output_list.append("temp_value_%d += temp_o_v_%d.value;"%(index,index))
        			output_list.append("temp_value_sqrd_%d += temp_o_v_%d.value*temp_o_v_%d.value;"%(index,index,index))
	
    		output_list.append("}") #End of Kernel For Loop
    
    		output_list.append("//**Copying the result to global memory**")
    		for index,d in enumerate(self.derivative):
      			output_list.append("value_%d[i] = temp_value_%d;"%(index,index))
      			output_list.append("value_sqrd_%d[i] = temp_value_sqrd_%d;"%(index,index))
      
    		output_list.append("}") #End of Kernel
    
		#Turning output list into output string
    		output_string = output_list[0]
    		for line in output_list[1:]: output_string = "%s\n%s"%(output_string,line)
    		output_string = "%s\n"%(output_string) #Adding newline to end of file
    		self.kernel_code_string = output_string
    
    		return output_list

	def generate_variable_declaration(self):
		"""Overriding the helper method of the same name in the Multicore CPU solver class
		
		Adding in struture for RNG
		"""
		output_list = MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.generate_variable_declaration(self)
    		if(self.random_number_generator=="mwc64x_boxmuller"): output_list.append("typedef struct{ cl_uint x; cl_uint c; } mwc64x_state_t;")
  
    		return output_list
  
	def compile(self,override=True,cleanup=True,debug=False):
    		"""Compiler method for OpenCL solver.

		In addition to compiling the host code, it compiles the OpenCL binary.

		Parameters
			override, cleanup, debug - same as in Mutlicore CPU class
		"""
		compile_flags = ["-lOpenCL","-I/opt/AMDAPP/include","-I/opt/nvidia/cuda/include","-fpermissive"]
    		if(debug): compile_flags.append("-ggdb")
    		if("darwin" in sys.platform):
      			compile_flags.remove("-lOpenCL")
      			compile_flags.extend(["-framework","OpenCL"])
    		
		result = MulticoreCPU_MonteCarlo.MulticoreCPU_MonteCarlo.compile(self,override,compile_flags,debug) #Compiling Host C Code
      
    
   		if (not "darwin" in sys.platform):
      			opencl_compile_flags = ""
      			if(self.random_number_generator=="mwc64x_boxmuller"): opencl_compile_flags = "%s -DMWC64X_BOXMULLER"%opencl_compile_flags
      			elif(self.random_number_generator=="taus_boxmuller" or self.random_number_generator=="taus_ziggurat"): opencl_compile_flags = "%s -DTAUS_BOXMULLER"%opencl_compile_flags
      			#path_string = ""
     			#path_string = "%s%s"%(self.platform.root_directory(),self.platform.platform_directory()) #os.getcwd()
      
      			opencl_compile_flags = "-DOPENCL_GPU %s "% (opencl_compile_flags)
      			self.program = pyopencl.Program(self.platform.context,self.kernel_code_string).build([opencl_compile_flags]) #Creating OpenCL program based upon Kernel
      
      
      			binary_kernel = self.program.get_info(pyopencl.program_info.BINARIES)[0] #Getting the binary code for the OpenCL code
			with open("%s/%s.clbin"%(os.path.join(self.platform.root_directory(),self.platform.platform_directory()),self.output_file_name),"w") as binary_kernel_file:
      				binary_kernel_file.write(binary_kernel)
     
    		return result
 
