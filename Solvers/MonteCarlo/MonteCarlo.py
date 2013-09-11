'''
Created on 11 July 2012

'''
import os,time,subprocess,sys,time,math,numpy.linalg,pickle,copy

class MonteCarlo:
    name = "monte_carlo_solver"
    paths = None
    threads = None
    
    reduce_underlyings = None
    
    platforms = []
    
    derivative = []
    derivative_attributes = []
    derivative_variables = []
    
    underlying = []
    underlying_attributes = []
    underlying_variables = []
    underlying_dependencies = []
    
    latency_model = None
    accuracy_model = None
    
    def __init__(self,derivative,paths,platform,reduce_underlyings=True):
        name = "monte_carlo_solver"
        self.platform = platform
        self.paths = paths
           
	self.solver_metadata = {"paths":self.paths}
        self.derivative = derivative
        self.reduce_underlyings = reduce_underlyings
        self.setup_underlyings(self.reduce_underlyings)
    
    """def __getstate__(self):
      state = self.__dict__.copy()
      return state"""
    
    def __setstate__(self,state):
      self.__dict__.update(state)
      self.generate_name()
      self.setup_underlyings(self.reduce_underlyings)
      
      #self.generate()
      #self.compile()
    
    def generate(self,override=True): pass
	
    def compile(self): pass
    
    def execute(self,cleanup=False): pass
    
    def generate_identifier(self): return ["//%s Generated by Monte Carlo Solver"%self.output_file_name]
    
    def cleanup(self): pass
    
    def setup_underlyings(self,reduce_underlyings):
	self.underlying = []
	
	underlying_list = []
        for d in self.derivative:
            for u in d.underlying:
                if(u.__dict__ not in underlying_list and reduce_underlyings):  
		  self.underlying.append(u) #Extracting unique underlyings from derivatives
		  underlying_list.append(u.__dict__)
                
                elif(reduce_underlyings):  #Making sure that equal underlyings are merged - TODO make this check stronger
                    index = self.derivative.index(d)
                    u_index = d.underlying.index(u)
                    new_u_index = underlying_list.index(u.__dict__)
                    d.underlying[u_index] = self.underlying[new_u_index]
                
                    #u_index = self.underlying.index(uu)
                    
                if((len(self.underlying)==0) or not reduce_underlyings): self.underlying.append(u)
         
        temp = [] #Generating Filename - based on underlyings,derivatives and platforms used
        self.generate_name()
	  
        for u in self.underlying:
          if u.name not in temp:
            count = 0
            for uu in self.underlying:
              if(uu.name==u.name): count = count + 1
    
            self.output_file_name = "%s_%s_%d" % (self.output_file_name,u.name[0:2],count) #First letter is used to keep names succinct
            temp.append(u.name)
    
        for d in self.derivative: 
          if d.name not in temp:
            count = 0
            for dd in self.derivative:
              if(dd.name==d.name): count = count + 1
      
            self.output_file_name = "%s_%s_%d" % (self.output_file_name,d.name[0:2],count)
            temp.append(d.name)
        
        self.underlying_dependencies = [] #Creating a dependency list for each underlying, detailing the derivative that depends on it
        for u in self.underlying:
            self.underlying_dependencies.append([])
            for d in self.derivative:
                if(u in d.underlying): self.underlying_dependencies[-1].append(self.derivative.index(d))

        #Extracting variables and attributes required during code generation, compilation and execution process
        self.underlying_attributes = []
        self.underlying_variables = []
        for u in self.underlying:
            self.underlying_attributes.append(u.__init__.__code__.co_varnames[1:])
            self.underlying_variables.append(self.attribute_stripper(self.underlying_attributes[-1],u.path_init.__code__.co_names))

        self.derivative_attributes = []
        self.derivative_variables = []
        for d in self.derivative:
            self.derivative_attributes.append(list(d.__init__.__code__.co_varnames[1:]))
            self.derivative_attributes[-1].remove("underlying")
            self.derivative_attributes[-1] = tuple(self.derivative_attributes[-1])
            self.derivative_variables.append(self.attribute_stripper(self.derivative_attributes[-1],d.path_init.__code__.co_names))
    
    def generate_name(self):
      self.output_file_name = "mc_solver"  
      self.output_file_name = ("%s_%s"%(self.output_file_name,self.platform.name))
    
    def populate_model(self,base_trial_paths,trial_steps):
      derivative_backup = self.derivative[:]
      underlying_backup = self.underlying[:]
      
      derivatives_with_shared_underlyings = []
      if(len(derivative_backup)>len(underlying_backup)): #Checking to see if there are any shared underlyings
	for u in underlying_backup:
	    temp_derivatives = []
	    for d in derivative_backup:
		if(u in d.underlying): temp_derivatives.append(d)
		    
	    if(len(temp_derivatives)>1): #This underlying has multiple derivatives that depend on it
		for d in temp_derivatives: derivatives_with_shared_underlyings.append(d) #recording the derivatives as ones which share underlyings
		
		"""for i in range(2**len(temp_derivatives)): #iterating over the permutations to capture
		    count = 0
		    for b in bin(i)[2:]:
			if(b=="1"): count = count+1
			
		    derivatives=[]
		    if(count>1):"""
		self.derivative = temp_derivatives
		self.setup_underlyings(True)
		self.generate()
		self.compile()
		
		trial_run_results = self.trial_run(base_trial_paths,trial_steps,self)
		accuracy = trial_run_results[0]
		latency = trial_run_results[1]

		latency_coefficients = self.generate_latency_prediction_function_coefficients(base_trial_paths,trial_steps,latency)
		accuracy_coefficients = self.generate_accuracy_prediction_function_coefficients(base_trial_paths,trial_steps,accuracy)

		name = "%s"%temp_derivatives[0].name[:2]
		for t_d in temp_derivatives[1:]: name = "%s_%s"%(name,t_d.name[:2])

		u.latency_model_coefficients["%s"%name] = latency_coefficients
		u.accuracy_model_coefficients["%s"%name] = accuracy_coefficients
      
      for d in derivative_backup:
	if(d not in derivatives_with_shared_underlyings):
	  self.derivative = [d]
	  self.setup_underlyings(True)
	  self.generate()
	  self.compile()
	  
	  trial_run_results = self.trial_run(base_trial_paths,trial_steps,self)
	  accuracy = trial_run_results[0]
	  latency = trial_run_results[1]
	  
	  latency_coefficients = self.generate_latency_prediction_function_coefficients(base_trial_paths,trial_steps,latency)
	  accuracy_coefficients = self.generate_accuracy_prediction_function_coefficients(base_trial_paths,trial_steps,accuracy)
	  
	  d.latency_model_coefficients.extend(latency_coefficients)
	  d.accuracy_model_coefficients.extend(accuracy_coefficients)    
    
      self.derivative = derivative_backup
      self.underlying = underlying_backup
      
      self.latency_model = self.generate_aggregate_latency_model()
      self.accuracy_model = self.generate_aggregate_accuracy_model()
      
    """def latency_model(self,paths):
      latency_sum = [lambda x: 0.0]
      #latency_sum = lambda x: 0.0
    
      temp_derivatives = self.derivative[:]
      if(len(self.derivative)>len(self.underlying)):
	for u in self.underlying:
	    count = 0
	    temp_temp_derivatives = []
	    for d in self.derivative:
		if(d.underlying[0]==u):
		    temp_temp_derivatives.append(d)
		    count = count + 1
	    
	    if(count>1):
		for d in temp_temp_derivatives: temp_derivatives.remove(d)
		name = "%s"%temp_temp_derivatives[0].name[:2]
		for t_d in temp_temp_derivatives[1:]: name = "%s_%s"%(name,t_d.name[:2])
		latency_sum.append(lambda x: u.latency_models["%s"%self.platform.name]["%s"%(name)](x))
      
      for d in temp_derivatives: latency_sum.append(lambda x: d.latency_model[self.platform.name](x))
      
      return lambda x: sum([l_s(x) for l_s in latency_sum])
    
    def accuracy_model(self,paths):
      
      return lambda x: max([a(x) for a in accuracies])"""
    
    
    def generate_aggregate_latency_model(self):
      latency_sum = [lambda x: 0.0]
    
      temp_derivatives = self.derivative[:]
      if(len(self.derivative)>len(self.underlying)):
	for u in self.underlying:
	    temp_temp_derivatives = []
	    for d in self.derivative:
		if(u in d.underlying):
		    temp_temp_derivatives.append(d)
	    
	    if(len(temp_temp_derivatives)>1):
		for d in temp_temp_derivatives: temp_derivatives.remove(d)
		name = "%s"%temp_temp_derivatives[0].name[:2]
		for t_d in temp_temp_derivatives[1:]: name = "%s_%s"%(name,t_d.name[:2])
		temp_u = copy.copy(u)
		#print "%d - %s"%(self.underlying.index(u)+1,name)
		latency_sum.append(lambda x: temp_u.latency_model("%s"%name[:],x))
      
      for d in temp_derivatives: latency_sum.append(lambda x: d.latency_model(x))
      
      return lambda x: sum([l_s(x) for l_s in latency_sum])
      
    def generate_aggregate_accuracy_model(self):
      accuracies = []
      
      temp_derivatives = self.derivative[:]
      if(len(self.derivative)>len(self.underlying)):
	for u in self.underlying:
	    temp_temp_derivatives = []
	    for d in self.derivative:
		if(u in d.underlying):
		    temp_temp_derivatives.append(d)
	    
	    if(len(temp_temp_derivatives)>1):
		for d in temp_temp_derivatives: temp_derivatives.remove(d)
		name = "%s"%temp_temp_derivatives[0].name[:2]
		for t_d in temp_temp_derivatives[1:]: name = "%s_%s"%(name,t_d.name[:2])
		temp_u = copy.copy(u)
		accuracies.append(lambda x: temp_u.accuracy_model("%s"%name,x))	
      
      #print len(temp_derivatives)
      for d in temp_derivatives: accuracies.append(lambda x: d.accuracy_model(x))
      
      return lambda x: max([a(x) for a in accuracies])
    
    def generate_pickle(self,file_name=""):
      self.latency_model = None
      self.accuracy_model = None
      if(file_name==""): pickle.dump(self,open("%s.p"%self.output_file_name,"wb"))
      else: pickle.dump(self,open("%s.p"%file_name,"wb"))
      
    """def generate_derivative_pickle(self,file_name=""):
      if(file_name==""): dumps(self.derivative,open("%s_derivative.p"%self.output_file_name,"wb"))
      else: dumps(self.derivative,open("%s_derivative.p"%file_name,"wb"))"""
    
    #Helper Methods
    def attribute_stripper(self,attributes,variables):
      """Helper Method used to remove all items in the first list from the second list, if present """
      variables = list(variables)
      for a in attributes:
	  if(variables.count(a)): variables.remove(a)
      
      return tuple(variables)
      
    def trial_run(self,paths,steps,solver,redudancy=10):
      accuracy = []
      latency = []

      path_set = numpy.arange(paths,paths*(steps+1),paths)
      for p in path_set: #Trial Runs to generate data needed for predicition functions
	solver.solver_metadata["paths"] = p
	for i in range(redudancy):
	  execution_output = solver.execute()
	  
	  latency.append((float(execution_output[-1])-float(execution_output[-2]),float(execution_output[-2]))) #(setup_time,activity_time)
	  
	  value = 0.0
	  std_error = 0.0
	  max_value = 0.0
	  for i,e_o in enumerate(execution_output[:-3]): #Selecting the highest relative error
	    if(not i%2): value = float(e_o)+0.00000000000001
	    else: 
	      std_error = float(e_o) 
	      error_prop = std_error #/value*100
	      if(error_prop>max_value): max_value = error_prop
	
	  accuracy.append(max_value)

      return [accuracy,latency]
      
    def generate_latency_prediction_function_coefficients(self,base_speculative_paths,data_points,latencies,degree=2,redudancy=10):
      speculative_matrix = numpy.zeros((data_points*redudancy,degree))
      
      for i in range(data_points*redudancy):
	  speculative_matrix[i][0] = (int(i/redudancy)+1)*base_speculative_paths
	  speculative_matrix[i][1] = 1.0 
	  
      #predicition_function_coefficients = numpy.linalg.lstsq(speculative_matrix,latencies)[0]
      
      temp_setup = 0.0
      temp_activity = []
      for i in range(data_points):
	for j in range(redudancy):
	  temp_setup = temp_setup + latencies[i*redudancy+j][0]
	  temp_activity.append(latencies[i*redudancy+j][1])
	  
      temp_activity_coefficients = numpy.linalg.lstsq(speculative_matrix,temp_activity)[0]
      predicition_function_coefficients = (temp_activity_coefficients[0],temp_setup/(redudancy*data_points) + temp_activity_coefficients[1])

      return predicition_function_coefficients

    def generate_accuracy_prediction_function_coefficients(self,base_speculative_paths,data_points,accuracy_data,degree=1,redudancy=10):
      speculative_matrix = numpy.zeros((data_points*redudancy,degree))
      
      for i in range(data_points*redudancy): #Creating NxN speculative matrix
	speculative_matrix[i][0] = ((int(i/redudancy)+1)*base_speculative_paths)**-0.5
	#speculative_matrix[i][1] = 1.0

      predicition_function_coefficients = numpy.linalg.lstsq(speculative_matrix,accuracy_data)[0]

      return predicition_function_coefficients
    