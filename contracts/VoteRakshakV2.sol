// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title VoteRakshakV2
 * @dev Enterprise-grade decentralized voting with:
 *      - Election Phase Management (CREATED → ACTIVE → ENDED → RESULT_DECLARED)
 *      - Multi-Election Support
 *      - Vote Receipt System
 */
contract VoteRakshakV2 {
    
    // ============ ENUMS ============
    enum ElectionPhase { CREATED, ACTIVE, ENDED, RESULT_DECLARED }
    
    // ============ STRUCTS ============
    struct Candidate {
        uint256 id;
        string name;
        uint256 voteCount;
    }
    
    struct Election {
        uint256 id;
        string name;
        string description;
        ElectionPhase phase;
        uint256 candidateCount;
        uint256 totalVotes;
        uint256 createdAt;
        uint256 startedAt;
        uint256 endedAt;
        bool exists;
    }
    
    struct VoteReceipt {
        uint256 receiptId;
        uint256 electionId;
        string visibleTag; // hashed enrollment, no candidate info
        uint256 timestamp;
        bool exists;
    }
    
    // ============ STATE VARIABLES ============
    address public admin;
    uint256 public electionCount;
    uint256 public globalReceiptCounter;
    
    // electionId => Election
    mapping(uint256 => Election) public elections;
    
    // electionId => candidateId => Candidate
    mapping(uint256 => mapping(uint256 => Candidate)) public candidates;
    
    // electionId => enrollment => hasVoted
    mapping(uint256 => mapping(string => bool)) public hasVoted;
    
    // electionId => faceHash => used
    mapping(uint256 => mapping(bytes32 => bool)) public usedFace;
    
    // electionId => faceHash => registered
    mapping(uint256 => mapping(bytes32 => bool)) public registeredFace;
    
    // electionId => enrollment => registered
    mapping(uint256 => mapping(string => bool)) public registeredEnrollment;
    
    // receiptId => VoteReceipt
    mapping(uint256 => VoteReceipt) public voteReceipts;
    
    // enrollment hash => receiptId (for user lookup without revealing identity)
    mapping(bytes32 => uint256[]) public userReceipts;
    
    // ============ EVENTS ============
    event ElectionCreated(uint256 indexed electionId, string name);
    event ElectionStarted(uint256 indexed electionId, uint256 timestamp);
    event ElectionEnded(uint256 indexed electionId, uint256 timestamp);
    event ResultsDeclared(uint256 indexed electionId, uint256 timestamp);
    event CandidateAdded(uint256 indexed electionId, uint256 candidateId, string name);
    event VoterRegistered(uint256 indexed electionId, string enrollment, bytes32 faceHash);
    event VoteCast(
        uint256 indexed electionId,
        uint256 indexed receiptId,
        bytes32 enrollmentHash,
        uint256 timestamp
    );
    
    // ============ MODIFIERS ============
    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin can perform this action");
        _;
    }
    
    modifier electionExists(uint256 _electionId) {
        require(elections[_electionId].exists, "Election does not exist");
        _;
    }
    
    modifier inPhase(uint256 _electionId, ElectionPhase _phase) {
        require(elections[_electionId].phase == _phase, "Invalid election phase");
        _;
    }
    
    // ============ CONSTRUCTOR ============
    constructor() {
        admin = msg.sender;
    }
    
    // ============ ADMIN FUNCTIONS ============
    
    /**
     * @dev Create a new election (starts in CREATED phase)
     */
    function createElection(
        string memory _name,
        string memory _description
    ) public onlyAdmin returns (uint256) {
        electionCount++;
        uint256 newId = electionCount;
        
        elections[newId] = Election({
            id: newId,
            name: _name,
            description: _description,
            phase: ElectionPhase.CREATED,
            candidateCount: 0,
            totalVotes: 0,
            createdAt: block.timestamp,
            startedAt: 0,
            endedAt: 0,
            exists: true
        });
        
        emit ElectionCreated(newId, _name);
        return newId;
    }
    
    /**
     * @dev Add candidate to an election (only in CREATED phase)
     */
    function addCandidate(
        uint256 _electionId,
        string memory _name
    ) public onlyAdmin electionExists(_electionId) inPhase(_electionId, ElectionPhase.CREATED) {
        Election storage election = elections[_electionId];
        election.candidateCount++;
        uint256 candidateId = election.candidateCount;
        
        candidates[_electionId][candidateId] = Candidate({
            id: candidateId,
            name: _name,
            voteCount: 0
        });
        
        emit CandidateAdded(_electionId, candidateId, _name);
    }
    
    /**
     * @dev Start election (CREATED → ACTIVE)
     */
    function startElection(
        uint256 _electionId
    ) public onlyAdmin electionExists(_electionId) inPhase(_electionId, ElectionPhase.CREATED) {
        require(elections[_electionId].candidateCount >= 2, "Need at least 2 candidates");
        
        elections[_electionId].phase = ElectionPhase.ACTIVE;
        elections[_electionId].startedAt = block.timestamp;
        
        emit ElectionStarted(_electionId, block.timestamp);
    }
    
    /**
     * @dev End election (ACTIVE → ENDED)
     */
    function endElection(
        uint256 _electionId
    ) public onlyAdmin electionExists(_electionId) inPhase(_electionId, ElectionPhase.ACTIVE) {
        elections[_electionId].phase = ElectionPhase.ENDED;
        elections[_electionId].endedAt = block.timestamp;
        
        emit ElectionEnded(_electionId, block.timestamp);
    }
    
    /**
     * @dev Declare results (ENDED → RESULT_DECLARED)
     */
    function declareResults(
        uint256 _electionId
    ) public onlyAdmin electionExists(_electionId) inPhase(_electionId, ElectionPhase.ENDED) {
        elections[_electionId].phase = ElectionPhase.RESULT_DECLARED;
        
        emit ResultsDeclared(_electionId, block.timestamp);
    }
    
    // ============ VOTER FUNCTIONS ============
    
    /**
     * @dev Register voter for an election
     */
    function registerVoter(
        uint256 _electionId,
        string memory _enrollment,
        bytes32 _faceHash
    ) public electionExists(_electionId) {
        // Can register in CREATED or ACTIVE phase
        require(
            elections[_electionId].phase == ElectionPhase.CREATED ||
            elections[_electionId].phase == ElectionPhase.ACTIVE,
            "Registration closed"
        );
        require(!registeredFace[_electionId][_faceHash], "Face already registered for this election");
        require(!registeredEnrollment[_electionId][_enrollment], "Enrollment already registered");
        
        registeredFace[_electionId][_faceHash] = true;
        registeredEnrollment[_electionId][_enrollment] = true;
        
        emit VoterRegistered(_electionId, _enrollment, _faceHash);
    }
    
    /**
     * @dev Cast vote (only in ACTIVE phase)
     * @return receiptId The unique vote receipt ID
     */
    function vote(
        uint256 _electionId,
        string memory _enrollment,
        bytes32 _faceHash,
        uint256 _candidateId
    ) public electionExists(_electionId) inPhase(_electionId, ElectionPhase.ACTIVE) returns (uint256) {
        require(!hasVoted[_electionId][_enrollment], "Already voted in this election");
        require(!usedFace[_electionId][_faceHash], "Face already used in this election");
        require(
            _candidateId > 0 && _candidateId <= elections[_electionId].candidateCount,
            "Invalid candidate"
        );
        
        // Record vote
        candidates[_electionId][_candidateId].voteCount++;
        hasVoted[_electionId][_enrollment] = true;
        usedFace[_electionId][_faceHash] = true;
        elections[_electionId].totalVotes++;
        
        // Generate receipt (no candidate info stored!)
        globalReceiptCounter++;
        uint256 receiptId = globalReceiptCounter;
        bytes32 enrollmentHash = keccak256(abi.encodePacked(_enrollment, _electionId));
        
        voteReceipts[receiptId] = VoteReceipt({
            receiptId: receiptId,
            electionId: _electionId,
            visibleTag: _generateTag(enrollmentHash),
            timestamp: block.timestamp,
            exists: true
        });
        
        userReceipts[enrollmentHash].push(receiptId);
        
        emit VoteCast(_electionId, receiptId, enrollmentHash, block.timestamp);
        
        return receiptId;
    }
    
    // ============ VIEW FUNCTIONS ============
    
    function getElection(uint256 _electionId) public view returns (
        uint256 id,
        string memory name,
        string memory description,
        ElectionPhase phase,
        uint256 candidateCount,
        uint256 totalVotes,
        uint256 createdAt,
        uint256 startedAt,
        uint256 endedAt
    ) {
        Election memory e = elections[_electionId];
        return (
            e.id, e.name, e.description, e.phase,
            e.candidateCount, e.totalVotes,
            e.createdAt, e.startedAt, e.endedAt
        );
    }
    
    function getCandidate(
        uint256 _electionId,
        uint256 _candidateId
    ) public view returns (uint256, string memory, uint256) {
        Candidate memory c = candidates[_electionId][_candidateId];
        return (c.id, c.name, c.voteCount);
    }
    
    function getElectionPhase(uint256 _electionId) public view returns (ElectionPhase) {
        return elections[_electionId].phase;
    }
    
    function getVoteReceipt(uint256 _receiptId) public view returns (
        uint256 receiptId,
        uint256 electionId,
        string memory visibleTag,
        uint256 timestamp,
        bool exists
    ) {
        VoteReceipt memory r = voteReceipts[_receiptId];
        return (r.receiptId, r.electionId, r.visibleTag, r.timestamp, r.exists);
    }
    
    function verifyVoteExists(uint256 _receiptId) public view returns (bool) {
        return voteReceipts[_receiptId].exists;
    }
    
    function getElectionCount() public view returns (uint256) {
        return electionCount;
    }
    
    // ============ INTERNAL FUNCTIONS ============
    
    function _generateTag(bytes32 _hash) internal pure returns (string memory) {
        bytes memory alphabet = "0123456789ABCDEF";
        bytes memory str = new bytes(8);
        for (uint256 i = 0; i < 4; i++) {
            str[i*2] = alphabet[uint8(_hash[i] >> 4)];
            str[i*2+1] = alphabet[uint8(_hash[i] & 0x0f)];
        }
        return string(str);
    }
}
