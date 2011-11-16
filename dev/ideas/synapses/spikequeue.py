"""
Spike queues following BEP-21
"""
from brian import *
from time import time

INITIAL_MAXSPIKESPER_DT = 1
# This is a 2D circular array, but also a SpikeMonitor

class SpikeQueue(SpikeMonitor):
    '''
    * Initialization * 

    Initialized with a source NeuronGroup, a Synapses object (from which it fetches the delays), a maximum delay
    
    Arguments
    ``source'' self explanatory
    ``synapses'' self explanatory

    Keywords
    ``max_delay'' in seconds
    ``maxevents'' Maximum initial number of events in each timestep. Notice that the structure will grow dynamically of there are more events than that, so you shouldn't bother. 


    * Circular 2D array structure * 
    
    A spike queue is implemented as a circular 2D array.
    
    * At the beginning or end of each timestep: queue.next()
    * To get all spikes: events=queue.peek()
      It returns the indexes of all synapses receiving an event.
    * When a presynaptic spike is emitted, the following is executed:
      queue.insert(delay,offset,target)
      where delay is the array of synaptic delays of targets in timesteps,
      offset is the array of offsets within each timestep,
      target is the array of synapse indexes of targets.
      The offset is used to solve the problem of multiple synapses with the
      same delay. For example, if there are two target synapses 7 and 9 with delay
      2 timesteps: queue.insert([2,2],[0,1],[7,9])
    
    Thus, offsets are determined by delays. They could be either precalculated
    (faster), or determined at run time (saves memory). Note that if they
    are determined at run time, then it may be possible to also vectorize over
    presynaptic spikes.
    
    * SpikeMonitor structure * 
    
    It automatically updates the underlying structure by instantiating the propagate() method of the SpikeMonitor
    
    Ideas:
    ------
    * remove the max_delay keyword and have the structure created with another
      method (at run time)
    '''
    def __init__(self, source, synapses, 
                 max_delay = 0, maxevents = INITIAL_MAXSPIKESPER_DT):
        # SpikeMonitor structure
        self.source = source #NeuronGroup
        self.synapses = synapses #Synapses
        
        self.max_delay = max_delay
        nsteps = int(np.floor((max_delay)/(self.source.clock.dt)))+1

        # number of time steps, maximum number of spikes per time step
        self.X = zeros((nsteps, maxevents), dtype = int) # target synapses
        self.X_flat = self.X.reshape(nsteps*maxevents,)
        self.currenttime = 0
        self.n = zeros(nsteps, dtype = int) # number of events in each time step
        
        super(SpikeQueue, self).__init__(source, 
                                         record = False)

    ################################ SPIKE QUEUE DATASTRUCTURE ######################
    def next(self):
        # Advance by one timestep
        self.n[self.currenttime]=0 # erase
        self.currenttime=(self.currenttime+1) % len(self.n)
        
    def peek(self):
        # Events in the current timestep
        return self.X[self.currenttime,:self.n[self.currenttime]]
    
    def offsets(self, delay):
        # Calculates offsets corresponding to a delay array
        #
        # Maybe it could be precalculated? (an int16 array?)
        I = argsort(delay)
        xs = delay[I]
        J = xs[1:]!=xs[:-1]
        #K = xs[1:]==xs[:-1]
        A = hstack((0, cumsum(J)))
        #B = hstack((0, cumsum(K)))
        B = hstack((0, cumsum(-J)))
        BJ = hstack((0, B[J]))
        ei = B-BJ[A]
        ofs = zeros_like(delay)
        ofs[I] = ei
        return ofs
        
    def insert(self, delay, offset, target):
        # Vectorized insertion of spike events
        # delay = delay in timestep
        # offset = offset within timestep
        # target = target synaptic index
        
        timesteps = (self.currenttime + delay) % len(self.n)
        
        # Compute new stack sizes:
        old_nevents = self.n[timesteps].copy() # because we need this for the final assignment, but we need to precompute the  new one to check for overflow
        self.n[timesteps] += offset+1 # that's a trick (to update stack size), plus we pre-compute it to check for overflow
        
        m = max(self.n[timesteps]) # If overflow, then at least one self.n is bigger than the size
        if (m >= self.X.shape[1]):
            self.resize(m)
        
        self.X_flat[(self.currenttime*self.X.shape[1]+offset+\
                     old_nevents)\
                     % len(self.X)]=target
        
    def resize(self, maxevents):
        '''
        Resizes the underlying data structure (number of columns = spikes per dt).
        max events will be rounded to the closest power of 2.
        '''
        
        # old and new sizes
        old_maxevents = self.X.shape[1]
        new_maxevents = 2**ceil(log2(maxevents))
        # new array
        newX = zeros((self.X.shape[0], new_maxevents), dtype = self.X.dtype)
        newX[:, :old_maxevents] = self.X[:, :old_maxevents] # copy old data
        
        self.X = newX
        self.X_flat = self.X.reshape(self.X.shape[0]*new_maxevents,)
        
        log_debug('spikequeue', 'Resizing SpikeQueue')
        
    def propagate(self, spikes):
        if len(spikes):
            # synapse identification, 
            # this seems ok in terms of speed even though I dont like the for loop. 
            # any idea? see stest_fastsynapseidentification.py
            synapses = []
            for i in spikes:
                # use hstack with arrays instead of lists
                synapses += list(nonzero(self.synapses._statevector._pre == i)[0]) # this is crazy!
                # we need a list/array of synapses for each presynaptic neuron
                # should we use array of arrays as objects?
                # and it could perhaps be on the SpikeQueue object

            if len(synapses):
                # delay getting:
                delay = self.synapses.delay[synapses]
                offsets = self.offsets(delay)
                self.insert(delay, offsets, synapses)
            
    ######################################## UTILS    
    def plot(self, display = True):
        for i in range(self.X.shape[0]):
            idx = (i + self.currenttime ) % self.X.shape[0]
            data = self.X[idx, :self.n[idx]]
            plot(idx * ones(len(data)), data, '.')
        if display:
            show()


    
'''
NOTE: the test code below is probably not working anymore since I changed the way it is created


The connection has arrays of synaptic variables (same as state matrix of
neuron groups). Two synaptic variables are the index of the postsynaptic neuron
and of the presynaptic neuron (i,j). (int32 or int16).

In addition, the connection must have, for each presynaptic neuron:
* list of target synapses (int32)
* corresponding delays in timesteps (int16)
* corresponding offsets (int16 is probably sufficient, or less)

These types (int32 etc) could be determined at construction time, or
at the time of conversion construction->connection (run time).

Same thing for postsynaptic neuron (for STDP)
This could also be determined at run time (depending on whether post=None or not)

Total memory:
* number of synapses * 12 * 2 (if bidirectional)
+ synaptic variables (weights)
'''

# We need to write some speed tests
if __name__=='__main__':
    queue=SpikeQueue(5,30)
    Nsynapses=4000*80 # in the CUBA example
    nspikes=160
    delays=randint(160,size=nspikes) # average number of spikes per dt in CUBA
    targets=randint(Nsynapses,size=nspikes)
    #print queue.offsets(delays)
    t1=time()
    for _ in range(10000): # 10000 timesteps per second
        d=queue.offsets(delays)
        queue.insert(delays,d,targets)
        queue.next()
        events=queue.peek()
        queue.plot()
    t2=time()
    print t2-t1